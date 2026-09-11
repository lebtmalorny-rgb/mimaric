#!/usr/bin/env python3.11
"""Parameterized network fault; plan locally, explicitly execute through SSH."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from remote_fault import atomic_write, locked, private_directory, validate

BOOTSTRAP = """import json, sys
payload = json.load(sys.stdin)
namespace = {"__name__": "powerops_remote"}
try:
    exec(compile(payload["source"], "<powerops-worker>", "exec"), namespace)
    result = namespace["dispatch"](payload["request"], payload["source"])
    print(json.dumps(result))
except Exception as exc:
    print(json.dumps({"phase": "ERROR", "result": "INCOMPLETE", "error": str(exc)}))
    sys.exit(2)
"""


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("plan", "start", "status", "restore"))
    result.add_argument("--host", required=True, help="SSH host or user@host")
    result.add_argument("--interface", required=True, help="exact Linux interface name")
    result.add_argument("--run-id", required=True, help="stable ID; reuse to observe the same run")
    result.add_argument("--intent-nonce", help="for a full stand runner fault: operations.fault.nonce from its report")
    result.add_argument("--duration", type=int, default=300, help="seconds, default 300; maximum 3600")
    result.add_argument("--execute", action="store_true", help="allow start to submit the outage")
    result.add_argument("--ssh-port", type=int, default=22)
    result.add_argument("--remote-python", default="python3.11")
    result.add_argument("--no-sudo", action="store_true", help="SSH session already runs as root")
    result.add_argument("--state-dir", type=Path, default=Path("artifacts/link-fault"),
                        help="persistent operator receipts; default artifacts/link-fault")
    return result


def validate_args(args):
    validate({"run_id": args.run_id, "interface": args.interface, "duration": args.duration})
    if args.intent_nonce is not None:
        validate(dict(run_id=args.run_id, interface=args.interface, duration=args.duration, nonce=args.intent_nonce))
    if not re.fullmatch(r"(?:[a-zA-Z0-9_][a-zA-Z0-9_.-]*@)?[a-zA-Z0-9][a-zA-Z0-9_.:-]*", args.host):
        raise ValueError("host must be an SSH hostname/IP, optionally prefixed by user@")
    if not 1 <= args.ssh_port <= 65535:
        raise ValueError("invalid SSH port")
    if not re.fullmatch(r"[a-zA-Z0-9/][a-zA-Z0-9_./-]*", args.remote_python):
        raise ValueError("invalid remote Python executable")


def call_remote(args, request):
    source = Path(__file__).with_name("remote_fault.py").read_text()
    remote = ([] if args.no_sudo else ["sudo", "-n", "--"]) + [args.remote_python, "-c", BOOTSTRAP]
    completed = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
         "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2",
         "-p", str(args.ssh_port), "--", args.host, shlex.join(remote)],
        input=json.dumps({"source": source, "request": request}),
        text=True, capture_output=True, timeout=25, check=False,
    )
    try:
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or "phase" not in result:
            raise ValueError("missing worker response")
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"no valid worker reply (SSH exit {completed.returncode}); outcome unknown") from exc
    if completed.returncode not in (0, 2):
        raise RuntimeError(f"SSH exit {completed.returncode}; outcome unknown")
    return result


def main(argv=None, transport=None):
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    try:
        validate_args(args)
    except ValueError as exc:
        argument_parser.error(str(exc))
    request = {"action": args.action,
               "fault": {"run_id": args.run_id, "interface": args.interface, "duration": args.duration}}
    if args.intent_nonce is not None:
        request['fault']['nonce'] = args.intent_nonce
    if args.action == "plan" or (args.action == "start" and not args.execute):
        print(json.dumps({"phase": "PLAN", "host": args.host, "request": request,
                          "note": "No SSH or changes. Add --execute to start. BMC power-on remains manual."}, indent=2))
        return 0
    transport = transport or call_remote
    result = None
    try:
        with locked(args.state_dir):
            run_dir = args.state_dir / args.run_id
            binding = {"host": args.host, "ssh_port": args.ssh_port, "fault": request["fault"]}
            if run_dir.exists():
                if run_dir.is_symlink():
                    raise ValueError("symlink receipt directory")
                original = json.loads((run_dir / "request.json").read_text())
                if original != binding:
                    raise ValueError("run-id is already bound to a different host/interface/duration")
            else:
                private_directory(run_dir)
                atomic_write(run_dir / "request.json", json.dumps(binding, indent=2) + "\n")
            try:
                # One request only. Remote journal also prevents a repeated start.
                result = transport(args, request)
            except (subprocess.SubprocessError, OSError, RuntimeError) as exc:
                result = {"phase": "UNKNOWN", "result": "INCOMPLETE", "error": str(exc),
                          "run_id": args.run_id,
                          "next": "Use status with the same parameters after access returns; do not create a new run-id."}
            atomic_write(run_dir / "result.json", json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError) as exc:
        # A local persistence error can also happen after remote submission.
        result = {"phase": "ERROR", "result": "INCOMPLETE", "error": str(exc),
                  "next": "Reconcile the same run-id on the target before starting another run."}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["phase"] == "UNKNOWN":
        return 3
    return 0 if result.get("result") == "COMPLETED" and not result.get("observation_error") else 2


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required")
    raise SystemExit(main())
