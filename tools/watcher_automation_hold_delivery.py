#!/usr/bin/env python3
"""Verify and replay the offline Watcher automation-hold delivery."""

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'hotfixes' / 'watcher-automation-hold' / 'manifest.json'


class DeliveryError(RuntimeError):
    """The delivery is invalid or cannot be replayed safely."""


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_file(root, value):
    path = pathlib.PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts:
        raise DeliveryError(f'artifact path must be relative: {value!r}')
    resolved = root.joinpath(*path.parts)
    if not resolved.is_file():
        raise DeliveryError(f'artifact is missing: {value}')
    return resolved


def _load_manifest(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DeliveryError(f'cannot read manifest: {error}') from None
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise DeliveryError('unsupported delivery manifest schema')
    if not isinstance(data.get('package'), dict):
        raise DeliveryError('manifest package entry is missing')
    if not isinstance(data.get('components'), dict) or not data['components']:
        raise DeliveryError('manifest components are missing')
    return data


def _artifact_entries(data):
    yield data['package']
    for component in data['components'].values():
        if not isinstance(component, dict):
            raise DeliveryError('invalid component entry')
        prerequisites = component.get('prerequisites', [])
        if not isinstance(prerequisites, list):
            raise DeliveryError('component prerequisites must be a list')
        yield from prerequisites
        patches = component.get('patches')
        if not isinstance(patches, list):
            raise DeliveryError('component patches must be a list')
        yield from patches


def verify_manifest(manifest_path=DEFAULT_MANIFEST):
    """Validate all local artifact hashes without changing any source tree."""
    manifest_path = pathlib.Path(manifest_path).resolve()
    data = _load_manifest(manifest_path)
    checked = []
    for entry in _artifact_entries(data):
        if not isinstance(entry, dict):
            raise DeliveryError('invalid artifact entry')
        expected = entry.get('sha256')
        if not isinstance(expected, str) or len(expected) != 64:
            raise DeliveryError('artifact SHA256 is missing or invalid')
        path = _relative_file(manifest_path.parent, entry.get('path', ''))
        actual = _sha256(path)
        if actual != expected:
            raise DeliveryError(f'SHA256 mismatch for {entry["path"]}')
        checked.append({'path': entry['path'], 'sha256': actual})
    return data, checked


def _copy_source(source, target):
    def ignore(directory, names):
        return {'.git'} if '.git' in names else set()

    shutil.copytree(source, target, symlinks=True, ignore=ignore)


def _git(root, *args):
    result = subprocess.run(
        ['git', '-C', str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or 'git failed'
        raise DeliveryError(detail)
    return result.stdout.strip()


def _index_tree(root, excluded_paths):
    _git(root, 'init', '-q')
    _git(root, '-c', 'core.autocrlf=false', 'add', '-Af', '--', '.')
    for value in excluded_paths:
        path = pathlib.PurePosixPath(value)
        if path.is_absolute() or '..' in path.parts:
            raise DeliveryError(f'excluded path must be relative: {value!r}')
        _git(root, 'rm', '--cached', '-q', '--ignore-unmatch', '--', value)
    return _git(root, 'write-tree')


def _snapshot_tree(source, excluded_paths):
    with tempfile.TemporaryDirectory(prefix='watcher-hold-base-') as directory:
        root = pathlib.Path(directory) / 'source'
        _copy_source(source, root)
        return _index_tree(root, excluded_paths)


def _excluded_state(root, excluded_paths):
    """Fingerprint excluded data so replay cannot silently alter local secrets."""
    state = {}
    for value in excluded_paths:
        pure = pathlib.PurePosixPath(value)
        if pure.is_absolute() or '..' in pure.parts:
            raise DeliveryError(f'excluded path must be relative: {value!r}')
        path = root.joinpath(*pure.parts)
        if path.is_symlink():
            state[value] = ('symlink', path.readlink().as_posix())
        elif path.is_file():
            state[value] = ('file', _sha256(path))
        elif path.is_dir():
            entries = []
            for child in sorted(path.rglob('*')):
                relative = child.relative_to(path).as_posix()
                if child.is_symlink():
                    entries.append((relative, 'symlink', child.readlink().as_posix()))
                elif child.is_file():
                    entries.append((relative, 'file', _sha256(child)))
                elif child.is_dir():
                    entries.append((relative, 'directory', None))
            state[value] = ('directory', entries)
        else:
            state[value] = ('missing', None)
    return state


def replay_component(manifest_path, component_name, source, output):
    """Copy one exact baseline, apply its patches, and prove the final tree."""
    manifest_path = pathlib.Path(manifest_path).resolve()
    data, _checked = verify_manifest(manifest_path)
    try:
        component = data['components'][component_name]
    except KeyError:
        raise DeliveryError(f'unknown component: {component_name}') from None
    source = pathlib.Path(source).resolve()
    output = pathlib.Path(output).resolve()
    if not source.is_dir():
        raise DeliveryError(f'source directory is missing: {source}')
    if output.exists():
        raise DeliveryError(f'output already exists: {output}')
    if output == source or source in output.parents:
        raise DeliveryError('output must not be inside the source directory')
    excluded_paths = component.get('excluded_paths', [])
    if not isinstance(excluded_paths, list):
        raise DeliveryError('excluded_paths must be a list')
    base_tree = _snapshot_tree(source, excluded_paths)
    if base_tree != component.get('base_tree'):
        raise DeliveryError(
            f'{component_name} base tree mismatch: expected '
            f'{component.get("base_tree")}, got {base_tree}')
    excluded_state = _excluded_state(source, excluded_paths)

    output.parent.mkdir(parents=True, exist_ok=True)
    _copy_source(source, output)
    try:
        _index_tree(output, excluded_paths)
        patches = [
            _relative_file(manifest_path.parent, entry['path'])
            for entry in component['patches']
        ]
        for patch in patches:
            _git(output, 'apply', '--check', '--whitespace=nowarn', str(patch))
            _git(output, 'apply', '--whitespace=nowarn', str(patch))
        if _excluded_state(output, excluded_paths) != excluded_state:
            raise DeliveryError('excluded path changed during patch replay')
        final_tree = _index_tree(output, excluded_paths)
        if final_tree != component.get('final_tree'):
            raise DeliveryError(
                f'{component_name} final tree mismatch: expected '
                f'{component.get("final_tree")}, got {final_tree}')
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return {
        'component': component_name,
        'base_tree': base_tree,
        'final_tree': final_tree,
        'patches': [entry['path'] for entry in component['patches']],
        'excluded_paths': excluded_paths,
    }


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=pathlib.Path, default=DEFAULT_MANIFEST)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify', help='verify package and patch SHA256 values')
    replay = commands.add_parser('replay', help='replay one component into a new directory')
    replay.add_argument('--component', required=True)
    replay.add_argument('--source', type=pathlib.Path, required=True)
    replay.add_argument('--output', type=pathlib.Path, required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == 'verify':
            _data, checked = verify_manifest(args.manifest)
            result = {'status': 'ok', 'artifacts': checked}
        else:
            result = replay_component(
                args.manifest, args.component, args.source, args.output)
            result['status'] = 'ok'
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except DeliveryError as error:
        print(json.dumps({'status': 'error', 'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
