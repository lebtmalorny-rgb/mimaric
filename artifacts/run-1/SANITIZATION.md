# Sanitization of run-1 artifacts

The artifacts in this directory were sanitized before public release so they
do not leak corp-specific identifiers (hostnames, IPs, UUIDs, endpoints,
operator names, RC paths).  This file explains the format and how to
desanitize when the recipient is authorized to see the real values.

## What was sanitized

| Category | Example placeholder | Real value (in key bundle) |
|----------|---------------------|----------------------------|
| Hostnames | `compute-02`, `control-06` | `ultra1-2`, `ultra1-6` |
| Host FQDN | `compute-02.local` | `ultra1-2.ultra1.test.pvs.un.sbt` |
| IP addresses | `10.0.0.146` | `10.101.25.146` |
| Test VM IP | `192.0.2.122` | `192.168.100.122` |
| UUIDs (test VM, ironic nodes, segment hosts) | `0000aaaa-aaaa-4aaa-8aaa-000000000001` | real v4 UUID |
| UUIDs (notifications, executions, migrations) | `11111111-1111-4111-8111-111111111111` (and similar) | real v4 UUID |
| Project identity | `<project-id>` | `975e519cfa61426ab8e40c5db90c295c` |
| User identity | `<user-id>` | `e1eae2c792834c21bbe8d39cfc193434` |
| Endpoint URLs | `https://compute.example.internal/v2.1` | `http://10.101.25.42:8774/v2.1` |
| Run IDs | `run-1-emergency`, `run-1-planned` | `ha-emergency-001`, `ha-planned-001` |
| RC paths | `/etc/<your-rc>.sh` | `/etc/kolla/admin-openrc.sh` |
| Operator | `<operator>` | `DVSokolov` |
| Segment name | `ha_segment` | `ha_cd` |

## What was NOT sanitized

- Code patches (`openstack_probe.py`, `remote_fault.py` and their `.orig`
  backups): no corp-specific data inside; only Python logic.
- File format, structure, JSON shape: identical to the original run, just
  with placeholder values.
- `examples/*.json` (upstream templates): untouched.

## Key bundle

The desanitize key bundle is **never** stored in this repo.  Its location is
`~/.local/share/powerops-stand/desanitize-key.json` on the operator host that
ran the sanitization.  Format:

```json
{
  "key_b64": "<Fernet key, 32 url-safe base64 bytes>",
  "mapping": {
    "uuid_to_placeholder": { "<real-uuid>": "<placeholder>", ... },
    "hostnames":            { ... },
    "ips":                  { ... },
    "endpoints":            { ... },
    "identities":           { ... },
    "run_ids":              { ... },
    "paths":                { ... },
    "names":                { ... },
    "segment_name":         { ... }
  },
  "version": 1,
  "note": "Sanitization key + mapping for run-1 artifacts. ..."
}
```

The `key_b64` is reserved for future use (e.g. encrypting the bundle itself
when stored on shared storage); the current reversal only needs `mapping`.

## Handling and transmission

- The bundle is sensitive: it inverts the sanitization, so anyone who gets
  both this repo and the bundle recovers the corp-specific identifiers.
- **NEVER** commit the bundle to git, push it to any remote, paste it into
  issue trackers, or email it in cleartext.
- The bundle is **git-ignored** by name (`desanitize.key.json`) and the
  matching `~/.local/share/powerops-stand/` path is outside any repo.
- For partner handoff, hand the bundle over via an encrypted channel —
  options that fit a typical ops workflow:
  - GPG-encrypted file emailed or shared through a corporate file share.
  - Password-protected archive whose password is shared via SMS / phone /
    second messenger.
  - Corporate secrets manager (Vault, AWS Secrets Manager, Bitwarden, ...).
- Log every transmission (who, when, channel, ticket id) — that record is
  part of the audit trail expected by the data owner.

## Reversal

To recover real values from sanitized artifacts, run:

```bash
# Dry-run first: shows which files would change.
python3.11 artifacts/run-1/desanitize.py \
    --key ~/.local/share/powerops-stand/desanitize-key.json \
    --root artifacts/run-1 \
    --dry-run

# Apply.
python3.11 artifacts/run-1/desanitize.py \
    --key ~/.local/share/powerops-stand/desanitize-key.json \
    --root artifacts/run-1 \
    --in-place
```

The script walks every file under `--root`, replaces placeholders back to
real values in-place (longest-placeholder-first to avoid partial collisions),
and skips the backup `.orig` files plus the reversal script itself.

## Rotation

When the corp-specific identifiers change (renamed host, new IPs, new
project) — or simply as a periodic hygiene measure — generate a fresh key
bundle and re-sanitize.  The old bundle then stops being useful even if
disclosed:

```bash
# 1. Re-sanitize (regenerates placeholders for the new mapping).
python3.11 /path/to/sanitize.py

# 2. Generate a fresh key bundle.
python3.11 - <<'PY'
import secrets, base64, json, pathlib
bundle = {
    "key_b64": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "mapping": {...},  # from the new sanitize step
    "version": 2,
    "note": "Rotated key for run-N. Old key invalid.",
}
out = pathlib.Path.home() / ".local/share/powerops-stand/desanitize-key.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
out.chmod(0o600)
PY

# 3. Destroy the old bundle (`shred -u` if available, then remove).
shred -u ~/.local/share/powerops-stand/desanitize-key.json.bak
```

## Verification

After a reversal, sanity-check a few obvious fields:

```bash
$ python3.11 -c "
import json
d = json.load(open('artifacts/run-1/task-run-1-emergency.json'))
print('host:', d['host'])
print('inventory_host:', d['inventory_host'])
print('server_ids:', d['server_ids'])
print('destination_hosts:', d['destination_hosts'])
"
host: ultra1-3.ultra1.test.pvs.un.sbt
inventory_host: ultra1-3
server_ids: ['e09d747f-c114-4d1f-ab89-b3d2f5d43bda']
destination_hosts: ['ultra1-2.ultra1.test.pvs.un.sbt']
```

If you see placeholders there, the key bundle is wrong (or out-of-date).
