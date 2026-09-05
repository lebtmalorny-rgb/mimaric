#!/usr/bin/env python3
"""Check three already-built images offline; never start their services.

Requires local Docker/Podman images. No pull, registry login, image build,
cloud API, runtime config mount or host network is used.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid


CHECK_CODE = r'''
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import mistral

expected = json.loads(sys.argv[1])
root = Path(mistral.__file__).resolve().parent
if not expected or 'mistral/services/powerops.py' not in expected:
    raise RuntimeError('Missing expected runtime manifest')
for name, digest in expected.items():
    if not name.startswith('mistral/') or '..' in Path(name).parts:
        raise RuntimeError('Invalid runtime manifest path')
    path = root / name.removeprefix('mistral/')
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Runtime file mismatch: ' + name)
print(json.dumps({'file_hashes': 'ok', 'files': len(expected)}), flush=True)
subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
subprocess.run([sys.executable, '-m', 'mistral.cmd.powerops_check'], check=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=['docker', 'podman'],
                        default='podman')
    parser.add_argument('--api-image', required=True)
    parser.add_argument('--engine-image', required=True)
    parser.add_argument('--executor-image', required=True)
    args = parser.parse_args()
    expected = json.loads(Path(__file__).with_name(
        'runtime-sha256.json').read_text())
    for role, reference in (('api', args.api_image),
                            ('engine', args.engine_image),
                            ('executor', args.executor_image)):
        # Resolve the local image first; subsequent runs are pinned to its ID.
        result = subprocess.run(
            [args.engine, 'image', 'inspect', '--format', '{{.Id}}', reference],
            check=True, text=True, capture_output=True, timeout=20,
        )
        image_id = result.stdout.strip()
        if not image_id or '\n' in image_id:
            raise RuntimeError('Expected exactly one local image ID')
        print(json.dumps({'role': role, 'image': reference,
                          'image_id': image_id}), flush=True)
        container_name = 'powerops-preflight-' + uuid.uuid4().hex
        try:
            subprocess.run([
                args.engine, 'run', '--rm', '--name', container_name,
                '--pull=never', '--network=none', '--read-only',
                '--tmpfs', '/tmp:rw,nosuid,nodev',
                '--entrypoint', '/var/lib/kolla/venv/bin/python', image_id,
                '-B', '-c', CHECK_CODE, json.dumps(expected, sort_keys=True),
            ], check=True, timeout=90)
        finally:
            # The CLI timeout does not necessarily stop its container.
            # This unique name belongs only to this disposable check.
            subprocess.run([args.engine, 'rm', '-f', container_name],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=20)
    print('PASS: all three local image contracts verified; live cloud untested')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        sys.exit(1)
