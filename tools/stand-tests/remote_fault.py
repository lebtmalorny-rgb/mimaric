"""Privileged Linux worker for an explicitly requested, bounded link outage.

No OpenStack calls, power actions, persistent network configuration or shell.
The operator sends this file over SSH; systemd runs the saved copy on the target.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path("/var/lib/powerops-link-test")
ID_PATTERN = r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}"


def validate(request):
    if not re.fullmatch(ID_PATTERN, request["run_id"]):
        raise ValueError("run-id: use 1-64 letters, digits, underscores or hyphens")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,14}", request["interface"]):
        raise ValueError("invalid Linux interface name")
    if request["interface"] == "lo":
        raise ValueError("loopback cannot be a fault target")
    if type(request["duration"]) is not int or not 1 <= request["duration"] <= 3600:
        raise ValueError("duration must be an integer between 1 and 3600 seconds")
    if 'nonce' in request and (not isinstance(request['nonce'], str) or not re.fullmatch(r'[0-9a-f]{32}', request['nonce'])):
        raise ValueError('invalid fault intent nonce')


def private_directory(path):
    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    if path.is_symlink() or not path.is_dir() or st.st_uid != os.geteuid() or st.st_mode & 0o077:
        raise ValueError(f"directory must be owned by current user and private: {path}")


def atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def locked(root):
    private_directory(root)
    flags = os.O_RDONLY if (root / ".lock").exists() else os.O_CREAT | os.O_RDWR
    fd = os.open(root / ".lock", flags | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r") as lock:
        deadline = time.monotonic() + 10
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("journal lock unavailable for 10 seconds") from None
                time.sleep(0.1)
        yield


def read_state(root, run_id):
    if not re.fullmatch(ID_PATTERN, run_id):
        raise ValueError("invalid run-id")
    path = root / run_id
    if path.is_symlink():
        raise ValueError("symlink journal directory")
    return json.loads((path / "state.json").read_text())


def save(root, state):
    atomic_write(root / state["request"]["run_id"] / "state.json",
                 json.dumps(state, indent=2, sort_keys=True) + "\n")


def identity(link, boot):
    return {"boot_id": boot, "ifname": link["ifname"],
            "ifindex": link["ifindex"], "address": link["address"]}


def checked_link(state, system):
    link = system.link(state["request"]["interface"])
    if identity(link, system.boot_id()) != state.get("reconciled_identity", state["identity"]):
        raise ValueError("boot or interface identity changed; manual reconciliation required")
    return link


def observe(state, system):
    try:
        state["current_link"] = checked_link(state, system)
        if state["phase"] == "RESTORED" and "UP" not in state["current_link"]["flags"]:
            state["observation_error"] = "interface is DOWN after this run ended; not overwriting later changes"
    except Exception as exc:
        state["observation_error"] = f"{type(exc).__name__}: {exc}"
    return state


class LinuxSystem:
    @staticmethod
    def command(argv):
        return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=10)

    def link(self, interface):
        result = self.command([self.binary("ip"), "-j", "-d", "link", "show", "dev", interface])
        links = json.loads(result.stdout)
        if len(links) != 1 or links[0]["ifname"] != interface:
            raise ValueError("interface lookup is not unique")
        return links[0]

    def set_link(self, interface, up):
        self.command([self.binary("ip"), "link", "set", "dev", interface, "up" if up else "down"])

    @staticmethod
    def binary(name):
        path = shutil.which(name)
        if not path:
            raise ValueError(f"required program not found: {name}")
        return path

    @staticmethod
    def boot_id():
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()

    @staticmethod
    def clock():
        return time.clock_gettime(time.CLOCK_BOOTTIME)

    wall = staticmethod(time.time)
    sleep = staticmethod(time.sleep)

    def launch(self, script, run_id, duration):
        python = str(Path(sys.executable).resolve())
        # ExecStopPost is parsed by systemd, not a shell. Keep its argv unambiguous.
        for value in (python, str(script), run_id):
            if not re.fullmatch(r"[a-zA-Z0-9_./-]+", value):
                raise ValueError("unsupported character in systemd worker path")
        self.command([
            self.binary("systemd-run"), "--quiet", "--service-type=exec",
            f"--unit=powerops-link-{run_id}", "--property=Restart=no",
            f"--property=RuntimeMaxSec={duration + 60}",
            "--property=TimeoutStartSec=15", "--property=TimeoutStopSec=150",
            "--property=UMask=0077",
            f"--property=ExecStopPost={python} {script} _restore {run_id}",
            python, str(script), "_work", run_id,
        ])


def start(request, source, root=ROOT, system=None):
    system = system or LinuxSystem()
    validate(request)
    with locked(root):
        run_dir = root / request["run_id"]
        if run_dir.exists():
            state = read_state(root, request["run_id"])
            if state["request"] != request:
                raise ValueError("run-id already belongs to different arguments")
            # Includes SUBMITTING: no repeat submission after a crash/lost reply.
            return dict(observe(state, system), new_submission=False)
        for path in root.iterdir():
            if path.is_dir() and (path / "state.json").exists():
                other = read_state(root, path.name)
                if other["phase"] != "RESTORED":
                    raise ValueError(f"host is held by active run {path.name}")
        link = system.link(request["interface"])
        if "UP" not in link["flags"] or "LOOPBACK" in link["flags"]:
            raise ValueError("target must initially be administratively UP and not loopback")
        state = {"schema": 1, "request": dict(request), "phase": "SUBMITTING",
                 "result": "INCOMPLETE", "identity": identity(link, system.boot_id()),
                 "initial_link": link, "created_at": system.wall(),
                 "worker_sha256": hashlib.sha256(source.encode()).hexdigest()}
        private_directory(run_dir)
        atomic_write(run_dir / "worker.py", source)
        save(root, state)
    try:
        system.launch(run_dir / "worker.py", request["run_id"], request["duration"])
    except Exception as exc:
        # The service may already be running. Preserve its state and leave it alone.
        with locked(root):
            state = read_state(root, request["run_id"])
            state["submit_error"] = f"{type(exc).__name__}: {exc}"
            save(root, state)
    return dict(status(request["run_id"], root, system), new_submission=True)


def status(run_id, root=ROOT, system=None):
    system = system or LinuxSystem()
    if not root.exists():
        raise ValueError("no journal exists on this host")
    with locked(root):
        state = read_state(root, run_id)
    return observe(state, system)


def reconcile(run_id, root=ROOT, system=None):
    """Close an old boot's fault journal after inspection, without changing links."""
    system = system or LinuxSystem()
    with locked(root):
        state = read_state(root, run_id)
        link = system.link(state['request']['interface'])
        boot = system.boot_id()
        original = state['identity']
        if boot == original['boot_id']:
            return observe(state, system)
        if link['ifname'] != original['ifname'] or link['address'] != original['address'] or 'UP' not in link['flags']:
            raise ValueError('new boot interface identity/UP is not confirmed')
        # No UP/DOWN calls and no replacement of original boot evidence.
        result = state['result'] if state['phase'] == 'RESTORED' else 'INTERRUPTED_BY_REBOOT'
        state.update(phase='RESTORED', result=result,
                     reconciled_identity=identity(link, boot), reconciled_at=system.wall())
        save(root, state)
        state['current_link'] = link
        return state


def restore(run_id, root=ROOT, system=None, reason="operator"):
    system = system or LinuxSystem()
    with locked(root):
        state = read_state(root, run_id)
        if state["phase"] == "RESTORED":
            return observe(state, system)
        if "apply_started" not in state:
            state.update(phase="RESTORED", result="NOT_APPLIED", restore_reason=reason)
            save(root, state)
            return state
        try:
            link = checked_link(state, system)
            completed = (reason == "elapsed" and state["phase"] == "DOWN"
                         and "UP" not in link["flags"] and system.clock() >= state["deadline"])
            state.update(phase="RESTORING", restore_reason=reason)
            try:
                save(root, state)
            except OSError as exc:
                # The durable APPLYING intent already authorizes restoring this
                # exact device. A full/read-only disk must not prevent link UP.
                state["journal_warning"] = str(exc)
            if "UP" not in link["flags"]:
                system.set_link(state["request"]["interface"], True)
            link = checked_link(state, system)
            if "UP" not in link["flags"]:
                raise ValueError("administrative UP not confirmed")
            state.update(phase="RESTORED", result="COMPLETED" if completed else "INTERRUPTED",
                         restored_at=system.wall(), final_link=link,
                         observed_seconds=max(0.0, system.clock() - state.get("down_started", state["apply_started"])))
        except Exception as exc:
            state.update(phase="NEEDS_OPERATOR", result="INCOMPLETE",
                         restore_error=f"{type(exc).__name__}: {exc}")
        try:
            save(root, state)
        except OSError as exc:
            state.update(persistence_error=str(exc), result="INCOMPLETE")
        return state


def work(run_id, root=ROOT, system=None):
    system = system or LinuxSystem()
    reason = "interrupted"
    try:
        with locked(root):
            state = read_state(root, run_id)
            if state["phase"] != "SUBMITTING":
                return state
            try:
                link = checked_link(state, system)
                if "UP" not in link["flags"]:
                    raise ValueError("interface changed before fault application")
            except Exception as exc:
                state.update(phase="NEEDS_OPERATOR", result="INCOMPLETE", error=str(exc))
                save(root, state)
                return state
            state.update(phase="APPLYING", apply_started=system.clock(), applied_at=system.wall())
            state["deadline"] = state["apply_started"] + state["request"]["duration"]
            save(root, state)
            system.set_link(state["request"]["interface"], False)
            if "UP" in checked_link(state, system)["flags"]:
                raise ValueError("administrative DOWN not confirmed")
            state.update(phase="DOWN", down_started=system.clock(), down_confirmed_at=system.wall())
            state["deadline"] = state["down_started"] + state["request"]["duration"]
            save(root, state)
        while True:
            with locked(root):
                state = read_state(root, run_id)
                if state["phase"] != "DOWN":
                    return state
                if "UP" in checked_link(state, system)["flags"]:
                    reason = "early_up"
                    break
                remaining = state["deadline"] - system.clock()
            if remaining <= 0:
                reason = "elapsed"
                break
            system.sleep(min(1.0, remaining))
    except Exception as exc:
        with locked(root):
            state = read_state(root, run_id)
            state["worker_error"] = f"{type(exc).__name__}: {exc}"
            try:
                save(root, state)
            except OSError:
                pass  # Restoration has priority over diagnostic persistence.
    return restore(run_id, root, system, reason)


def recover(run_id, root=ROOT, system=None):
    """Systemd stop hook: three bounded, idempotent restoration attempts."""
    system = system or LinuxSystem()
    for attempt in range(3):
        try:
            state = restore(run_id, root, system, "systemd_stop")
        except (OSError, ValueError) as exc:
            state = {"phase": "NEEDS_OPERATOR", "result": "INCOMPLETE",
                     "run_id": run_id, "restore_error": str(exc)}
        if state["phase"] == "RESTORED":
            return state
        if attempt < 2:
            system.sleep(2)
    return state


def dispatch(request, source):
    if sys.version_info < (3, 11) or sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("target requires Linux, root and Python 3.11+")
    validate(request["fault"])
    action = request["action"]
    fault = request["fault"]
    if action == "start":
        return start(fault, source)
    # Verify all parameters even for restoration; wrong target arguments cannot mutate.
    state = status(fault["run_id"])
    if state["request"] != fault:
        raise ValueError("arguments do not match stored run")
    if action == "restore":
        return restore(fault["run_id"])
    if action == "status":
        return state
    if action == "reconcile":
        return reconcile(fault["run_id"])
    raise ValueError("unknown action")


if __name__ == "__main__":
    if os.geteuid() != 0 or sys.platform != "linux":
        raise SystemExit("internal worker requires root on Linux")
    action, run_id = sys.argv[1:]
    if action == "_work":
        result = work(run_id)
    elif action == "_restore":
        result = recover(run_id)
    else:
        raise SystemExit("internal worker action required")
    print(json.dumps(result))
    raise SystemExit(0 if result["phase"] == "RESTORED" else 2)
