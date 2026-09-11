#!/usr/bin/python3
"""Fixed-action local recovery entry point; no controller connection needed."""
import json
import sys
import re

from powerops_firewall_runtime import execute


if __name__ == '__main__':
    if sys.argv[1:] not in (['recover-expired'], ['recover-boot']):
        raise SystemExit('Only recover-expired and recover-boot are accepted')
    try:
        result = execute(sys.argv[1], {})
        result.pop('nonce', None)
        print(json.dumps(result))
    except Exception as exc:
        # No arbitrary command/API exception text in the journal.
        code = str(exc) if re.fullmatch(r'[A-Z_]+', str(exc)) else 'RECOVERY_FAILED'
        print(code + ': state retained for the next retry', file=sys.stderr)
        raise SystemExit(1)
