"""Bounded Linux observations. No shell and no firewall mutation operations."""
from datetime import datetime, timezone
import os
import selectors
import signal
import subprocess
import time


COMMANDS = {
    'addresses': ['ip', '-j', 'address', 'show'],
    'routes_v4': ['ip', '-j', '-4', 'route', 'show', 'table', 'all'],
    'routes_v6': ['ip', '-j', '-6', 'route', 'show', 'table', 'all'],
    'ss': ['ss', '-H', '-lntu'],
    'firewalld_state': ['firewall-cmd', '--state'],
    'firewalld_active_zones': ['firewall-cmd', '--get-active-zones'],
    'firewalld_runtime_zones': ['firewall-cmd', '--list-all-zones'],
    'firewalld_permanent_zones': ['firewall-cmd', '--permanent', '--list-all-zones'],
    'firewalld_runtime_policies': ['firewall-cmd', '--list-all-policies'],
    'firewalld_permanent_policies': ['firewall-cmd', '--permanent', '--list-all-policies'],
    'nft': ['nft', '-j', 'list', 'ruleset'],
    'iptables': ['iptables-save'],
    'ip6tables': ['ip6tables-save'],
    'services': ['systemctl', 'show', 'firewalld.service', 'nftables.service',
                 '--property=Id,ActiveState,SubState,UnitFileState'],
    'bridge_netfilter': ['sysctl', 'net.bridge.bridge-nf-call-iptables',
                        'net.bridge.bridge-nf-call-ip6tables'],
}


def validate_limits(timeout, max_bytes):
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise ValueError('timeout must be an integer between 1 and 120 seconds')
    if type(max_bytes) is not int or not 1 <= max_bytes <= 4194304:
        raise ValueError('max_bytes must be an integer between 1 and 4194304')


def run_readonly(argv, timeout=10, max_bytes=262144):
    """Internal runner; argv is never taken from module/user parameters."""
    validate_limits(timeout, max_bytes)
    result = {'argv': list(argv), 'rc': None, 'stdout': '', 'stderr': '',
              'timed_out': False, 'truncated': False, 'available': True}
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True,
            env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'},
        )
    except OSError as exc:
        result.update(available=False, stderr='Cannot execute command (errno %s)' % exc.errno)
        return result

    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    deadline = time.monotonic() + timeout
    group_stopped = False

    def kill_owned_group():
        nonlocal group_stopped
        if group_stopped:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        group_stopped = True

    with selectors.DefaultSelector() as selector:
        for name in buffers:
            stream = getattr(proc, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        try:
            while selector.get_map() or proc.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    result['timed_out'] = True
                    kill_owned_group()
                    break
                for key, _ in selector.select(min(0.1, remaining)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    buffer = buffers[key.data]
                    room = max_bytes - len(buffer)
                    buffer.extend(data[:room])
                    if len(data) > room:
                        result['truncated'] = True
                        kill_owned_group()
                if result['truncated']:
                    break
            try:
                result['rc'] = proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                result['timed_out'] = True
                kill_owned_group()
        finally:
            # Includes descendants still holding pipes after the parent exited.
            kill_owned_group()
            proc.stdout.close()
            proc.stderr.close()
    for name, buffer in buffers.items():
        result[name] = bytes(buffer).decode('utf-8', errors='ignore')
    return result


def collect_snapshot(timeout=10, max_bytes=262144):
    validate_limits(timeout, max_bytes)
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'commands': {name: run_readonly(argv, timeout=timeout, max_bytes=max_bytes)
                     for name, argv in COMMANDS.items()},
    }
