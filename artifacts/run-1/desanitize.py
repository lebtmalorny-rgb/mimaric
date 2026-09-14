#!/usr/bin/env python3.11
"""Reverse sanitization for artifacts/run-1/.

Reads a sanitization key bundle from $REPO/.secrets/desanitize-key.json
(the same directory tree as this script's parent/parent/parent/.secrets)
and walks every file under the artifacts directory, replacing each
placeholder back with its real value.

Usage:
    # Defaults: key at $REPO/.secrets/desanitize-key.json, root at
    # $(git rev-parse --show-toplevel)/artifacts/run-1
    python3.11 desanitize.py             # dry-run by default
    python3.11 desanitize.py --in-place  # write changes

    # Override paths explicitly:
    python3.11 desanitize.py \
        --key "$REPO/.secrets/desanitize-key.json" \
        --root "$REPO/artifacts/run-1"

    # Round-trip from any directory:
    REPO="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    python3.11 "$REPO/artifacts/run-1/desanitize.py" --dry-run

The key bundle is .gitignore'd at the repo root (.secrets/) -- never
commit it.  See ../SANITIZATION.md for transmission and rotation rules.
"""
import argparse
import json
import re
import sys
from pathlib import Path


def default_repo_root() -> Path:
    """Repo root: this script lives at <repo>/artifacts/run-1/."""
    return Path(__file__).resolve().parent.parent.parent


def default_key_path() -> Path:
    return default_repo_root() / ".secrets" / "desanitize-key.json"


def default_root_path() -> Path:
    return default_repo_root() / "artifacts" / "run-1"


def load_bundle(key_path: Path) -> dict:
    if not key_path.is_file():
        sys.exit(
            f"key bundle not found: {key_path}\n"
            f"  hint: copy or regenerate from operator host; "
            f"see SANITIZATION.md"
        )
    bundle = json.loads(key_path.read_text())
    if "key_b64" not in bundle or "mapping" not in bundle:
        sys.exit("invalid key bundle: missing key_b64 or mapping")
    return bundle


def flatten_replacements(mapping: dict) -> list[tuple[str, str]]:
    """mapping has structure: {category: {real: placeholder, ...}}.

    Sanitization replaced real -> placeholder.  We invert to
    (placeholder, real) so desanitize can substitute back.
    """
    pairs = []
    for category in ("uuid_to_placeholder", "hostnames", "ips", "endpoints",
                     "identities", "run_ids", "paths", "names", "segment_name"):
        for real, placeholder in mapping.get(category, {}).items():
            pairs.append((placeholder, real))
    return pairs


def desanitize(text: str, pairs: list[tuple[str, str]]) -> tuple[str, int]:
    """Replace each placeholder back with the real value.

    Longest-first ordering prevents shorter placeholders from being eaten
    inside longer ones (e.g. "control-06" inside "host-control-06.local").
    Word-boundary anchors require non-word characters (or string edges)
    around the placeholder so we never touch a substring of a larger
    token (e.g. "control-06" inside "host-control-06.local").
    """
    pairs_sorted = sorted(pairs, key=lambda p: -len(p[0]))
    hits = 0
    for placeholder, real in pairs_sorted:
        # When the placeholder starts and ends with alphanumerics, we
        # can use \b word boundaries to ensure we only match the
        # standalone token.  When it contains non-word characters
        # (e.g. '.local', '-test'), \b would not match; fall back to
        # a plain substring replace (these are unique enough by
        # construction).
        if placeholder[:1].isalnum() and placeholder[-1:].isalnum():
            pat = re.compile(r"\b" + re.escape(placeholder) + r"\b")
            new_text, n = pat.subn(real, text)
        else:
            n = text.count(placeholder)
            new_text = text.replace(placeholder, real) if n else text
        if n:
            hits += n
            text = new_text
    return text, hits


# Files we never touch: this script, its docs, code backups whose
# contents must stay byte-identical to the originals.
SKIP_NAMES = {"desanitize.py", "SANITIZATION.md", "README.md",
              "openstack_probe.py.orig", "remote_fault.py.orig"}


def walk(root: Path, pairs: list[tuple[str, str]], dry: bool) -> None:
    files = sorted(p for p in root.rglob("*") if p.is_file())
    total_hits = 0
    for p in files:
        if p.name in SKIP_NAMES:
            continue
        text = p.read_text()
        new, hits = desanitize(text, pairs)
        if hits:
            tag = "DRY" if dry else "WRITE"
            print(f"{tag}  {p.relative_to(root)}  ({hits} replacements)")
            total_hits += hits
            if not dry:
                p.write_text(new)
    print(f"Total: {total_hits} replacements across {len(files)} files.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", type=Path, default=default_key_path(),
                    help="Path to desanitize-key.json "
                         "(default: $REPO/.secrets/desanitize-key.json).")
    ap.add_argument("--root", type=Path, default=default_root_path(),
                    help="Root directory to desanitize "
                         "(default: $REPO/artifacts/run-1).")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Print what would change without writing.")
    mode.add_argument("--in-place", action="store_true",
                      help="Actually write the changes back.")
    args = ap.parse_args()

    bundle = load_bundle(args.key)
    pairs = flatten_replacements(bundle["mapping"])
    if not pairs:
        sys.exit("no replacements found in key bundle")

    walk(args.root, pairs, dry=not args.in_place)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
