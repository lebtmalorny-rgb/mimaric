#!/usr/bin/env python3.11
"""Reverse sanitization for artifacts/run-1/.

Reads a sanitization key bundle (separate from this repo) and walks every
.json/.md/.ini under the artifacts directory, replacing each placeholder
back with its real value.  Run with --dry-run to preview; --in-place to
write.

Usage:
    python3.11 desanitize.py \
        --key ~/.local/share/powerops-stand/desanitize-key.json \
        --root artifacts/run-1 \
        [--dry-run | --in-place]
"""
import argparse
import json
import sys
from pathlib import Path


def load_bundle(key_path: Path) -> dict:
    """Load key bundle from outside the repo."""
    if not key_path.is_file():
        sys.exit(f"key bundle not found: {key_path}")
    bundle = json.loads(key_path.read_text())
    if "key_b64" not in bundle or "mapping" not in bundle:
        sys.exit("invalid key bundle: missing key_b64 or mapping")
    return bundle


def flatten_replacements(mapping: dict) -> list[tuple[str, str]]:
    """Flatten nested mapping dict to (placeholder, real) pairs.

    Mapping has the structure:
      {"uuid_to_placeholder": {real: placeholder, ...},
       "hostnames": {real: placeholder, ...},
       ...}
    The sanitization replaced real -> placeholder.  To reverse, we replace
    placeholder -> real.
    """
    pairs = []
    for category in ("uuid_to_placeholder", "hostnames", "ips", "endpoints",
                     "identities", "run_ids", "paths", "names", "segment_name"):
        for real, placeholder in mapping.get(category, {}).items():
            pairs.append((placeholder, real))
    return pairs


def desanitize(text: str, pairs: list[tuple[str, str]]) -> tuple[str, int]:
    """Replace each placeholder back with the real value.  Longer first."""
    pairs_sorted = sorted(pairs, key=lambda p: -len(p[0]))
    hits = 0
    for placeholder, real in pairs_sorted:
        if placeholder in text:
            hits += text.count(placeholder)
            text = text.replace(placeholder, real)
    return text, hits


def walk(root: Path, pairs: list[tuple[str, str]], dry: bool) -> None:
    files = sorted(p for p in root.rglob("*") if p.is_file())
    total_hits = 0
    for p in files:
        # Skip files that are clearly already-public templates.
        if p.name in {"openstack_probe.py.orig", "remote_fault.py.orig",
                      "desanitize.py", "SANITIZATION.md", "README.md"}:
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
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--key", type=Path, required=True,
                   help="Path to desanitize-key.json (NOT in this repo).")
    p.add_argument("--root", type=Path, required=True,
                   help="Root directory to desanitize (e.g. artifacts/run-1).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Print what would change without writing.")
    mode.add_argument("--in-place", action="store_true",
                      help="Actually write the changes back.")
    args = p.parse_args()

    bundle = load_bundle(args.key)
    pairs = flatten_replacements(bundle["mapping"])
    if not pairs:
        sys.exit("no replacements found in key bundle")

    walk(args.root, pairs, dry=not args.in_place)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
