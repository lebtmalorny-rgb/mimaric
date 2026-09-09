#!/usr/bin/env python3
"""Bounded, read-only PowerOps diagnostics; Python 3.8+ standard library only.

The host/api modes write only sanitized JSON to stdout. Ansible manages its
normal temporary script; report mode writes one private text file on the operator.
No shell, service mutation, arbitrary container exec or configuration dump.
"""
import argparse
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
import uuid


UTC = dt.timezone.utc
MASK = "[REDACTED]"
SERVICES = ("masakari", "ironic", "nova", "mistral", "consul", "etcd", "rabbitmq")
CONTAINER = re.compile(r"^(?:masakari|ironic|nova|mistral|consul|etcd|rabbitmq)(?:[_-][A-Za-z0-9_.-]+)?$")
HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,252}$")
SENSITIVE = re.compile(r"password|passwd|secret|token|authorization|cookie|private.?key", re.I)
STAMP = re.compile(r"\b(\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:\d\d)?)")
APACHE = re.compile(r"\[(\d\d/[A-Za-z]{3}/\d{4}:\d\d:\d\d:\d\d [+-]\d{4})\]")


def redact(text, extra_secrets=()):
    text = str(text)
    for secret in sorted(extra_secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, MASK)
    # Decode complete JSON before touching embedded quoted log messages.
    if text.lstrip().startswith(("{", "[")):
        try:
            structured = json.loads(text)
        except (ValueError, RecursionError):
            pass
        else:
            return json.dumps(sanitize(structured, extra_secrets), ensure_ascii=False)
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)",
                  MASK, text, flags=re.S)
    text = re.sub(r"(?i)([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    def mask_header(match):
        # Preserve only the complete Ironic policy-denial form, never arbitrary
        # Authorization values (including Bearer/Basic after 'Rejecting').
        if (match.group(1).lower().startswith('authorization:')
                and match.string[max(0, match.start() - 10):match.start()].lower() == 'rejecting '
                and re.fullmatch(r'baremetal:[a-z_][a-z_:.]* is disallowed by policy[ \t]*',
                                 match.group(2))):
            return match.group(0)
        return match.group(1) + MASK

    text = re.sub(r"(?im)((?:x-auth-token|x-subject-token|authorization|set-cookie|cookie)[\"']?\s*:\s*)([^\n]*)",
                  mask_header, text)
    key = r"[\w.-]*(?:password|passwd|secret|token)[\w.-]*"
    # In prefixed/partial JSON, do not guess where an escaped secret ends.
    text = re.sub(r"(?i)(" + key + r"[\"']?\s*[:=]\s*)\\+[\"'][^\n]*",
                  lambda m: m.group(1) + MASK, text)
    # Honor escaped quotes in prefixed JSON/log values. An unfinished quoted
    # value is masked through end-of-line, including a dangling backslash.
    value = r'''(?:"(?:\\[^\n]|[^"\\\n])*(?:"|\\?(?=\n|\Z))|'(?:\\[^\n]|[^'\\\n])*(?:'|\\?(?=\n|\Z))|[^"'\s,;&}\]\n]+)'''
    text = re.sub(r"(?i)([\"']?(?:" + key + r")[\"']?\s*[:=]\s*)" + value,
                  lambda m: m.group(1) + '"' + MASK + '"', text)
    text = re.sub(r"(?i)(--[\w-]*(?:password|passwd|secret|token)[\w-]*\s+)" + value,
                  lambda m: m.group(1) + MASK, text)
    return text


def sanitize(value, extra_secrets=()):
    if isinstance(value, dict):
        return {str(k): MASK if SENSITIVE.search(str(k)) or str(k).lower() in
                {"driver_info", "env", "environment", "user_data", "os-ext-srv-attr:user_data"}
                else sanitize(v, extra_secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, extra_secrets) for v in value]
    return redact(value, extra_secrets) if isinstance(value, str) else value


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00").replace(",", "."))
    if result.tzinfo is None:
        raise ValueError("Time must include Z or an explicit UTC offset")
    return result.astimezone(UTC)


def validate_config(raw):
    now = dt.datetime.now(UTC)
    cfg = dict(since=iso(now - dt.timedelta(hours=1)), until=iso(now),
               log_timezone="+00:00", notification_id="", segment_id="", node_id="",
               server_ids=[], compute_hosts=[], log_root="/var/log/kolla",
               command_timeout=25, api_timeout=20, total_timeout=240,
               max_command_bytes=262144, max_file_bytes=524288,
               max_scan_bytes=8388608, max_total_bytes=8388608,
               max_files=48, max_containers=24, max_vmoves=50, container_log_lines=3000,
               max_notifications=10, max_servers=30, max_segments=20, max_migrations=30,
               workflow_ids=[], max_workflows=10, max_tasks=30)
    if not isinstance(raw, dict) or set(raw) - set(cfg):
        raise ValueError("Unknown diagnostic settings or non-object config")
    cfg.update(raw)
    since, until = parse_time(cfg["since"]), parse_time(cfg["until"])
    if since >= until:
        raise ValueError("since must be earlier than until")
    cfg.update(since=iso(since), until=iso(until))
    if not re.fullmatch(r"[+-](?:0\d|1[0-4]):[0-5]\d", cfg["log_timezone"]):
        raise ValueError("log_timezone must be an explicit offset, e.g. +00:00")
    for key in ("notification_id", "segment_id", "node_id"):
        if cfg[key]:
            cfg[key] = str(uuid.UUID(cfg[key]))
    for key in ("server_ids", "compute_hosts", "workflow_ids"):
        if not isinstance(cfg[key], list) or len(cfg[key]) > 100:
            raise ValueError(key + " must be a list with at most 100 entries")
    cfg["server_ids"] = list(dict.fromkeys(str(uuid.UUID(v)) for v in cfg["server_ids"]))
    cfg["workflow_ids"] = list(dict.fromkeys(str(uuid.UUID(v)) for v in cfg["workflow_ids"]))
    if any(not isinstance(h, str) or not HOST.fullmatch(h) for h in cfg["compute_hosts"]):
        raise ValueError("Invalid compute host name")
    if not isinstance(cfg["log_root"], str) or not os.path.isabs(cfg["log_root"]):
        raise ValueError("log_root must be an absolute path")
    for key in ("command_timeout", "api_timeout", "total_timeout", "max_command_bytes",
                "max_file_bytes", "max_scan_bytes", "max_total_bytes", "max_files",
                "max_containers", "max_vmoves", "container_log_lines", "max_notifications", "max_servers",
                "max_segments", "max_workflows", "max_tasks", "max_migrations"):
        if isinstance(cfg[key], bool) or not isinstance(cfg[key], int) or cfg[key] <= 0:
            raise ValueError(key + " must be a positive integer")
    if cfg["total_timeout"] > 3600 or cfg["command_timeout"] > 120:
        raise ValueError("Timeout exceeds the collection safety limit")
    if max(cfg[k] for k in ("max_scan_bytes", "max_file_bytes", "max_command_bytes",
                            "max_total_bytes")) > 67108864:
        raise ValueError("Byte limit exceeds 64 MiB")
    if (cfg["max_files"] > 256 or cfg["max_containers"] > 128 or cfg["max_vmoves"] > 100
            or cfg["max_notifications"] > 50 or cfg["max_servers"] > 100
            or cfg['max_segments'] > 100 or cfg['max_workflows'] > 50 or cfg['max_tasks'] > 100
            or cfg['max_migrations'] > 100):
        raise ValueError("Collection item limit is too large")
    return cfg


def run_command(argv, timeout, max_bytes, extra_secrets=()):
    start = time.monotonic()
    data = bytearray()
    status = "ok"
    process = None
    try:
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    status = "timeout"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), min(65536, max_bytes + 1 - len(data)))
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        data.extend(chunk)
                if len(data) > max_bytes:
                    status = "output_limit"
                    break
            if status == "ok":
                # A child can close stdout and then hang: wait is also bounded.
                try:
                    process.wait(timeout=max(0.01, timeout - (time.monotonic() - start)))
                except subprocess.TimeoutExpired:
                    status = "timeout"
    except FileNotFoundError:
        status = "missing_command"
    except OSError as exc:
        status = "error"
        data.extend(str(exc).encode())
    finally:
        if process:
            if status != "ok":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
            process.stdout.close()
    rc = process.returncode if process else None
    if status == "ok" and rc:
        status = "error"
    raw = bytes(data)
    incomplete_line = status in {"timeout", "output_limit"} and raw and not raw.endswith(b"\n")
    if incomplete_line:
        # An unfinished URL may not yet contain '@'; keeping it can expose userinfo.
        raw = raw.rpartition(b"\n")[0]
    output = redact(raw.decode("utf-8", "replace"), extra_secrets).encode()[:max_bytes].decode("utf-8", "ignore")
    return dict(status=status, rc=rc, duration_seconds=round(time.monotonic() - start, 3),
                truncated=len(data) > max_bytes or bool(incomplete_line),
                incomplete_line_omitted=bool(incomplete_line), output=output)


def log_stamp(line, offset):
    match = STAMP.search(line)
    if match:
        value = match.group(1)
        if not re.search(r"(?:Z|[+-]\d\d:\d\d)$", value):
            value += offset
        try:
            return parse_time(value)
        except ValueError:
            return None
    match = APACHE.search(line)
    if match:
        try:
            return dt.datetime.strptime(match.group(1), "%d/%b/%Y:%H:%M:%S %z").astimezone(UTC)
        except ValueError:
            return None
    return None


def read_log(path, cfg, extra_secrets=()):
    result = dict(path=str(path), status="ok", records=0, output="", scan_truncated=False,
                  truncated=False)
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Not a regular log file")
            cap = cfg["max_scan_bytes"]
            if str(path).endswith(".gz"):
                with gzip.GzipFile(fileobj=source) as compressed:
                    raw = compressed.read(cap + 1)
                result["scan_truncated"] = len(raw) > cap
                raw = raw[:cap]
                result["scan_strategy"] = "gzip_prefix"
            else:
                source.seek(max(0, info.st_size - cap))
                raw = source.read(cap)
                result["scan_truncated"] = info.st_size > cap
                if result["scan_truncated"]:
                    raw = raw.partition(b"\n")[2]
                result["scan_strategy"] = "plain_tail"
            result["file_size_bytes"] = info.st_size
        if raw and not raw.endswith(b"\n"):
            raw = raw.rpartition(b"\n")[0]
            result["truncated"] = True
            result["incomplete_line_omitted"] = True
        since, until = parse_time(cfg["since"]), parse_time(cfg["until"])
        selected, active, stamped = [], False, False
        for line in raw.decode("utf-8", "replace").splitlines(keepends=True):
            stamp = log_stamp(line, cfg["log_timezone"])
            if stamp is not None:
                stamped = True
                active = since <= stamp <= until
                result["records"] += int(active)
            if active:
                selected.append(line)
        if not stamped:
            result["status"] = "unparsed_time"
            # Explicitly marked fallback, not evidence of membership in the window.
            text = raw.decode("utf-8", "replace")
        else:
            text = "".join(selected)
        clean = redact(text, extra_secrets).encode()
        result["truncated"] = result["truncated"] or len(clean) > cfg["max_file_bytes"]
        result["output"] = clean[:cfg["max_file_bytes"]].decode("utf-8", "ignore")
    except (OSError, ValueError, EOFError) as exc:
        result.update(status="read_error", output=redact(str(exc), extra_secrets))
    return result


def discover_logs(root, limit, errors=None):
    candidates = []
    errors = errors if errors is not None else []
    for service in SERVICES:
        directory = Path(root) / service
        try:
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode):
                continue
            for path in directory.iterdir():
                try:
                    info = path.lstat()
                except OSError as exc:
                    if len(errors) < limit:
                        errors.append(dict(path=str(path), status='discovery_error', output=str(exc)))
                    continue
                if re.search(r"\.log(?:\.[A-Za-z0-9_.-]+)?$", path.name) and stat.S_ISREG(info.st_mode):
                    candidates.append((info.st_mtime, str(path), path))
        except FileNotFoundError:
            # Not every node runs every service. Other available logs still matter.
            continue
        except OSError as exc:
            if len(errors) < limit:
                errors.append(dict(path=str(directory), status='discovery_error', output=str(exc)))
    return [row[2] for row in sorted(candidates, reverse=True)[:limit]]


def api_jobs(cfg):
    base = ["openstack"]
    jobs = []

    def add(name, args, fields=()):
        command = base + args + ["-f", "json"]
        for field in fields:
            command.extend(["-c", field])
        jobs.append((name, command))

    if cfg["notification_id"]:
        add("notification", ["notification", "show", cfg["notification_id"]])
        add("vmoves", ["notification", "vmove", "list", cfg["notification_id"],
                       "--limit", str(cfg["max_vmoves"])])
    else:
        add("notifications", ["notification", "list", "--sort", "created_at:desc", "--limit", "20"])
    if cfg["segment_id"]:
        add("segment", ["segment", "show", cfg["segment_id"]])
        add("segment_hosts", ["segment", "host", "list", cfg["segment_id"]])
    fields = ["uuid", "name", "power_state", "target_power_state", "last_error",
              "provision_state", "network_interface", "maintenance"]
    if cfg["node_id"]:
        add("ironic_node", ["baremetal", "node", "show", cfg["node_id"], "--fields"] + fields, fields)
    for host in cfg["compute_hosts"]:
        # Ironic accepts node names. This is an API identifier, never a DNS lookup.
        add("ironic_node_" + host, ["baremetal", "node", "show", host, "--fields"] + fields, fields)
        add("nova_service_" + host, ["compute", "service", "list", "--host", host, "--service", "nova-compute"])
        add("servers_on_" + host, ["server", "list", "--all-projects", "--host", host], ["ID", "Name", "Status"])
        # Include VMs that left this host before the first snapshot. Migration
        # history has source/destination filters; no source-host SSH is needed.
        add("host_migrations_" + host, ["--os-compute-api-version", "2.66",
            "server", "migration", "list", "--host", host,
            "--changes-since", cfg['since'], "--changes-before", cfg['until'],
            "--limit", str(cfg['max_migrations'])])
    for server in cfg["server_ids"]:
        add("server_" + server, ["server", "show", server],
            ["id", "name", "status", "OS-EXT-SRV-ATTR:host", "OS-EXT-SRV-ATTR:instance_name",
             "OS-EXT-STS:task_state", "OS-EXT-STS:vm_state", "OS-EXT-STS:power_state"])
        add("events_" + server, ["server", "event", "list", server])
        add("migrations_" + server, ["server", "migration", "list", "--server", server])
    return jobs


def row_field(row, *names):
    """OSC table column names and API JSON keys differ between plugin versions."""
    if not isinstance(row, dict):
        return None
    normalized = {re.sub(r'[^a-z0-9]', '', str(k).lower()): v for k, v in row.items()}
    for name in names:
        value = normalized.get(re.sub(r'[^a-z0-9]', '', name.lower()))
        if value is not None:
            return value
    return None


def error_kind(text):
    value = str(text).lower()
    for kind, patterns in (
        ('auth_config', ('missing value auth-url', 'missing value username', 'missing value password',
                         'missing value project', 'you must provide an auth', 'could not find cloud')),
        ('authentication', ('http 401', 'http/1.1 401', 'unauthorized')),
        ('permission', ('http 403', 'forbidden', 'disallowed by policy', 'value redacted - requires')),
        ('missing_plugin', ('unknown command', 'is not an openstack command')),
        ('dns', ('could not resolve hostname', 'name or service not known', 'name resolution')),
        ('host_key', ('host key verification failed', 'remote host identification has changed')),
        ('ssh_auth', ('permission denied (publickey',)),
        ('sudo', ('sudo: a password is required', 'missing sudo password', 'not in the sudoers')),
        ('timeout', ('connection timed out', 'operation timed out')),
        ('connection', ('connection refused', 'no route to host', 'network is unreachable')),
    ):
        if any(pattern in value for pattern in patterns):
            return kind
    return None


class Collector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.deadline = time.monotonic() + cfg["total_timeout"]
        self.remaining = cfg["max_total_bytes"]
        self.secrets = [v for k, v in os.environ.items() if SENSITIVE.search(k) and len(v) >= 8]
        self.report = dict(schema_version=2, started_at=iso(dt.datetime.now(UTC)),
                           window={k: cfg[k] for k in ("since", "until", "log_timezone")},
                           scope={k: cfg[k] for k in ('compute_hosts', 'segment_id', 'notification_id', 'node_id')},
                           checks=[], logs=[], observations=[])

    def command(self, name, argv):
        started = dt.datetime.now(UTC)
        if time.monotonic() >= self.deadline or self.remaining <= 0:
            result = dict(status="skipped_budget", rc=None, output="", truncated=False)
        else:
            timeout = self.cfg["command_timeout"]
            if argv[0] == 'openstack':
                timeout = min(timeout, self.cfg['api_timeout'])
            result = run_command(argv, min(timeout, self.deadline - time.monotonic()),
                                 min(self.remaining, self.cfg["max_command_bytes"]), self.secrets)
        result["name"] = name
        result.update(started_at=iso(started), ended_at=iso(dt.datetime.now(UTC)))
        kind = error_kind(result['output'])
        if result['status'] in ('timeout', 'missing_command', 'skipped_budget'):
            kind = result['status']
        if kind:
            result['error_kind'] = kind
        if argv[0] == 'openstack' and 'value redacted - requires' in result['output'].lower():
            result['status'] = 'restricted_fields'
        line_cap = 500 if name.endswith("_journal") else (
            self.cfg["container_log_lines"] if name.startswith("container_log_") else None)
        if line_cap is not None and len(result["output"].splitlines()) >= line_cap:
            result["truncated"] = True
            result["line_limit_reached"] = line_cap
        self.remaining -= len(result["output"].encode())
        self.report["checks"].append(result)
        return result

    def rows(self, result, cap=None):
        if result['status'] != 'ok' or result.get('truncated'):
            return []
        try:
            rows = json.loads(result['output'])
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ValueError('Expected an array of objects')
            if cap is not None and len(rows) >= cap:
                result.update(truncated=True, item_limit=cap)
            return rows if cap is None else rows[:cap]
        except (ValueError, TypeError) as exc:
            result.update(status='parse_error', parse_error=str(exc))
            return []

    def observation(self, text):
        self.report['observations'].append(redact(text, self.secrets))

    def identifier(self, row, result, *names):
        try:
            return str(uuid.UUID(str(row_field(row, *names))))
        except (ValueError, TypeError, AttributeError):
            result.update(status='parse_error', parse_error='Missing or invalid UUID in API row')
            return None

    def in_window(self, row):
        stamp = row_field(row, 'generated_time', 'created_at')
        if not isinstance(stamp, str):
            return None
        try:
            # Masakari/Nova API timestamps without offsets are UTC.
            if not re.search(r'(?:Z|[+-]\d\d:\d\d)$', stamp):
                stamp += 'Z'
            value = parse_time(stamp)
            return parse_time(self.cfg['since']) <= value <= parse_time(self.cfg['until'])
        except ValueError:
            return None

    def api(self, previous=None):
        self.report["kind"] = "api"
        self.report['snapshot'] = 'after' if previous else 'before'
        servers = list(self.cfg['server_ids'])
        workflows = list(self.cfg['workflow_ids'])
        if previous:
            try:
                previous_report = json.loads(Path(previous).read_text())['report']
                if isinstance(previous_report, str):
                    previous_report = json.loads(previous_report)
                identifiers = previous_report.get('discovered_server_ids', [])
                if not isinstance(identifiers, list) or len(identifiers) > 100:
                    raise ValueError('Invalid previous server list')
                servers.extend(str(uuid.UUID(str(v))) for v in identifiers)
                previous_workflows = previous_report.get('selected_workflow_ids', [])
                if not isinstance(previous_workflows, list) or len(previous_workflows) > 100:
                    raise ValueError('Invalid previous workflow list')
                workflows.extend(str(uuid.UUID(str(v))) for v in previous_workflows)
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
                self.report['checks'].append(dict(name='previous_snapshot', status='parse_error',
                                                  output=redact(str(exc), self.secrets)))
        self.command("openstack_version", ["openstack", "--version"])
        # This read-only request checks the actual CLI credential source (including
        # clouds.yaml); inspecting OS_AUTH_URL alone would reject valid cloud profiles.
        probe = self.command('api_preflight', ['openstack', 'segment', 'list',
                                             '--limit', str(self.cfg['max_segments']), '-f', 'json'])
        if probe.get('error_kind') in ('auth_config', 'missing_command'):
            self.observation('Remaining API reads skipped: CLI authentication/configuration is unavailable; host logs are still collected.')
            self.report['discovered_server_ids'] = list(dict.fromkeys(servers))[:self.cfg['max_servers']]
            return self.finish()
        host_ids = {}
        segment_ids = [self.cfg['segment_id']] if self.cfg['segment_id'] else []
        if not segment_ids:
            for row in self.rows(probe, self.cfg['max_segments']):
                identifier = self.identifier(row, probe, 'uuid', 'id')
                if identifier:
                    segment_ids.append(identifier)
        self.report['discovered_segment_ids'] = list(dict.fromkeys(segment_ids))
        jobs = []
        for segment_id in self.report['discovered_segment_ids']:
            jobs += [('segment_' + segment_id, ['openstack', 'segment', 'show', segment_id, '-f', 'json']),
                     ('segment_hosts_' + segment_id, ['openstack', 'segment', 'host', 'list', segment_id, '-f', 'json'])]
        jobs += api_jobs(dict(self.cfg, notification_id='', server_ids=[], segment_id=''))
        ambiguous_hosts = set()
        for name, argv in jobs:
            if name == 'notifications':
                continue
            result = self.command(name, argv)
            if name.startswith('segment_hosts_'):
                for row in self.rows(result):
                    host = row_field(row, 'name')
                    if host in self.cfg['compute_hosts']:
                        identifier = self.identifier(row, result, 'uuid')
                        if identifier:
                            if host in host_ids and host_ids[host] != identifier:
                                ambiguous_hosts.add(host)
                            else:
                                host_ids[host] = identifier
                        self.observation('%s: Masakari on_maintenance=%s (snapshot, not pre-failure state).' %
                                         (host, row_field(row, 'on_maintenance')))
            elif name.startswith('servers_on_'):
                for row in self.rows(result, self.cfg['max_servers']):
                    identifier = self.identifier(row, result, 'id', 'uuid')
                    if identifier:
                        servers.append(identifier)
            elif name.startswith('host_migrations_'):
                for row in self.rows(result, self.cfg['max_migrations']):
                    identifier = self.identifier(row, result, 'server_uuid', 'instance_uuid', 'server_id')
                    if identifier:
                        servers.append(identifier)
            elif name.startswith('nova_service_'):
                for row in self.rows(result):
                    self.observation('%s: Nova status=%s state=%s.' %
                                     (row_field(row, 'host'), row_field(row, 'status'), row_field(row, 'state')))

        notifications = [self.cfg['notification_id']] if self.cfg['notification_id'] else []
        for host in self.cfg['compute_hosts']:
            if host not in host_ids or host in ambiguous_hosts:
                self.report['checks'].append(dict(name='notifications_' + host, status='skipped_scope',
                                                  output='Cannot resolve this compute host to one unambiguous Masakari segment-host UUID.'))
                continue
            result = self.command('notifications_' + host, ['openstack', 'notification', 'list',
                                  '--filters', 'source_host_uuid=' + host_ids[host],
                                  '--sort', 'created_at:desc', '--limit', str(self.cfg['max_notifications']), '-f', 'json'])
            for row in self.rows(result, self.cfg['max_notifications']):
                identifier = self.identifier(row, result, 'notification_uuid', 'uuid', 'id')
                if not identifier:
                    continue
                within = self.in_window(row)
                if within is False:
                    self.observation('Notification %s outside requested log window; retained in list only.' % identifier)
                else:
                    notifications.append(identifier)
                    if within is None:
                        self.observation('Notification %s has no usable list timestamp; checking details.' % identifier)
        if not self.cfg['compute_hosts'] and not notifications:
            result = self.command('notifications', ['openstack', 'notification', 'list', '--sort', 'created_at:desc',
                                  '--limit', str(self.cfg['max_notifications']), '-f', 'json'])
            for row in self.rows(result, self.cfg['max_notifications']):
                identifier = self.identifier(row, result, 'notification_uuid', 'uuid', 'id')
                if identifier and self.in_window(row) is not False:
                    notifications.append(identifier)
        self.report['selected_notification_ids'] = list(dict.fromkeys(notifications))
        if not notifications:
            self.observation('No notification selected in this bounded snapshot; this does not prove no failure occurred.')
        for identifier in self.report['selected_notification_ids']:
            name = 'notification' if identifier == self.cfg['notification_id'] else 'notification_' + identifier
            result = self.command(name, ['openstack', 'notification', 'show', identifier, '-f', 'json'])
            if result['status'] == 'ok' and not result.get('truncated'):
                try:
                    detail = json.loads(result['output'])
                    if not isinstance(detail, dict):
                        raise ValueError('Notification detail must be an object')
                    if self.in_window(detail) is False:
                        self.observation('Notification %s outside requested log window; not evidence of the current incident.' % identifier)
                    if row_field(detail, 'source_host_uuid') not in host_ids.values() and self.cfg['compute_hosts']:
                        self.observation('Notification %s source is not confirmed among requested compute hosts.' % identifier)
                except (ValueError, TypeError) as exc:
                    result.update(status='parse_error', parse_error=str(exc))
            name = 'vmoves' if identifier == self.cfg['notification_id'] else 'vmoves_' + identifier
            moves = self.command(name, ['openstack', 'notification', 'vmove', 'list', identifier,
                                       '--limit', str(self.cfg['max_vmoves']), '-f', 'json'])
            for row in self.rows(moves, self.cfg['max_vmoves']):
                move_id = self.identifier(row, moves, 'uuid', 'vmove_uuid', 'id')
                if not move_id:
                    continue
                detail = self.command('vmove_' + move_id, ['openstack', 'notification', 'vmove', 'show',
                                                         identifier, move_id, '-f', 'json'])
                candidates = [row]
                if detail['status'] == 'ok' and not detail.get('truncated'):
                    try:
                        candidates.append(json.loads(detail['output']))
                    except ValueError:
                        detail['status'] = 'parse_error'
                for candidate in candidates:
                    if row_field(candidate, 'instance_uuid', 'server_uuid', 'server_id'):
                        server = self.identifier(candidate, detail, 'instance_uuid', 'server_uuid', 'server_id')
                        if server:
                            servers.append(server)
        servers = list(dict.fromkeys(servers))
        if len(servers) > self.cfg['max_servers']:
            self.report['checks'].append(dict(name='server_discovery', status='item_limit',
                                              output='Server detail limit reached; not all discovered VMs were read.'))
        self.report['discovered_server_ids'] = servers[:self.cfg['max_servers']]
        for name, argv in api_jobs(dict(self.cfg, notification_id='', node_id='', segment_id='',
                                       compute_hosts=[], server_ids=self.report['discovered_server_ids'])):
            if name != 'notifications':
                self.command(name, argv)
        self.workflows(workflows)
        return self.finish()

    def workflows(self, explicit):
        """Bounded PowerOps workflow discovery; no action or workflow execution."""
        selected = list(dict.fromkeys(explicit))
        listing = self.command('workflows', ['openstack', 'workflow', 'execution', 'list',
                               '--sort_keys', 'created_at', '--sort_dirs', 'desc',
                               '--limit', str(self.cfg['max_workflows']), '-f', 'json'])
        for row in self.rows(listing, self.cfg['max_workflows']):
            name = row_field(row, 'workflow_name')
            if not isinstance(name, str) or not name.startswith(('power_ops.', 'powerops.')):
                continue
            state = str(row_field(row, 'state')).upper()
            if self.in_window(row) is False and state not in ('RUNNING', 'PAUSED'):
                continue
            identifier = self.identifier(row, listing, 'id')
            if not identifier or identifier in selected:
                continue
            data = self.command('workflow_input_' + identifier,
                                ['openstack', 'workflow', 'execution', 'input', 'show', identifier])
            if data['status'] != 'ok' or data.get('truncated'):
                continue
            try:
                payload = json.loads(data['output'])
                if not isinstance(payload, dict):
                    raise ValueError('Workflow input is not an object')
                if not self.cfg['compute_hosts'] or payload.get('host') in self.cfg['compute_hosts']:
                    selected.append(identifier)
                else:
                    self.observation('Workflow %s input does not match the requested hosts; details not selected.' % identifier)
            except (ValueError, TypeError) as exc:
                data.update(status='parse_error', parse_error=str(exc))
        if len(selected) > self.cfg['max_workflows']:
            self.report['checks'].append(dict(name='workflow_discovery', status='item_limit',
                                              output='Workflow detail limit reached.'))
        self.report['selected_workflow_ids'] = selected[:self.cfg['max_workflows']]
        for identifier in self.report['selected_workflow_ids']:
            self.command('workflow_' + identifier, ['openstack', 'workflow', 'execution', 'show', identifier, '-f', 'json'])
            if identifier in explicit:
                self.command('workflow_input_' + identifier,
                             ['openstack', 'workflow', 'execution', 'input', 'show', identifier])
            self.command('workflow_output_' + identifier,
                         ['openstack', 'workflow', 'execution', 'output', 'show', identifier])
            tasks = self.command('tasks_' + identifier, ['openstack', 'task', 'execution', 'list', identifier,
                                 '--limit', str(self.cfg['max_tasks']), '-f', 'json'])
            for row in self.rows(tasks, self.cfg['max_tasks']):
                if str(row_field(row, 'state')).upper() not in ('ERROR', 'RUNNING', 'PAUSED'):
                    continue
                task = self.identifier(row, tasks, 'id')
                if task:
                    self.command('task_' + task, ['openstack', 'task', 'execution', 'show', task, '-f', 'json'])
                    self.command('task_result_' + task, ['openstack', 'task', 'execution', 'result', 'show', task])

    def host(self):
        self.report["kind"] = "host"
        for name, args in [
            ("hostname", ["hostname", "-f"]), ("utc_time", ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]),
            ("uptime", ["uptime"]),
            ("time_sync", ["timedatectl", "show", "--property=NTPSynchronized", "--property=Timezone", "--property=TimeUSec"]),
            ("chrony_tracking", ["chronyc", "tracking"]), ("chrony_sources", ["chronyc", "-n", "sources"]),
            ("clock_journal", ["journalctl", "--utc", "--no-pager", "-u", "chronyd", "-u", "systemd-timesyncd",
                               "--since", self.cfg["since"].replace("T", " ").replace("Z", " UTC"),
                               "--until", self.cfg["until"].replace("T", " ").replace("Z", " UTC"), "-n", "500"]),
        ]:
            self.command(name, args)
        window = ['--utc', '--no-pager', '--since', self.cfg['since'].replace('T', ' ').replace('Z', ' UTC'),
                  '--until', self.cfg['until'].replace('T', ' ').replace('Z', ' UTC'), '-n', '500']
        self.command('podman_version', ['podman', '--version'])
        self.command('kernel_journal', ['journalctl', '-k'] + window)
        self.command('podman_journal', ['journalctl', '-u', 'podman.service', '-u', 'podman.socket'] + window)
        self.command('conmon_journal', ['journalctl', '_COMM=conmon'] + window)
        containers = self.command("containers", ["podman", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"])
        names = [line.split("\t")[0] for line in containers["output"].splitlines()
                 if CONTAINER.fullmatch(line.split("\t")[0])]
        if len(names) > self.cfg["max_containers"]:
            containers["truncated"] = True
        for name in names[:self.cfg["max_containers"]]:
            # Explicit allowlist of inspect fields: never .Config, .Env or healthcheck output.
            self.command("container_state_" + name,
                         ["podman", "inspect", "--format",
                          "id={{.Id}} image_id={{.Image}} image={{.ImageName}} status={{.State.Status}} "
                          "running={{.State.Running}} pid={{.State.Pid}} exit_code={{.State.ExitCode}} "
                          "error={{json .State.Error}} oom_killed={{.State.OOMKilled}} "
                          "started={{.State.StartedAt}} finished={{.State.FinishedAt}}", name])
        files = discover_logs(self.cfg["log_root"], self.cfg["max_files"] + 1, self.report['logs'])
        if not files:
            self.report["logs"].append(dict(path=self.cfg["log_root"], status="no_log_files", output=""))
        if len(files) > self.cfg["max_files"]:
            self.report["logs"].append(dict(path=self.cfg["log_root"], status="file_limit", output=""))
        for path in files[:self.cfg["max_files"]]:
            if time.monotonic() >= self.deadline or self.remaining <= 0:
                self.report["logs"].append(dict(path=str(path), status="skipped_budget", output=""))
                continue
            config = dict(self.cfg, max_file_bytes=min(self.remaining, self.cfg["max_file_bytes"]))
            result = read_log(path, config, self.secrets)
            self.remaining -= len(result["output"].encode())
            self.report["logs"].append(result)
        for name in names[:self.cfg["max_containers"]]:
            self.command("container_log_" + name,
                         ["podman", "logs", "--timestamps", "--since", self.cfg["since"], "--until", self.cfg["until"],
                          "--tail", str(self.cfg["container_log_lines"]), name])
        return self.finish()

    def finish(self):
        self.report["ended_at"] = iso(dt.datetime.now(UTC))
        return sanitize(self.report, self.secrets)


def write_report(directory, expected, require_final_api=False):
    directory = Path(directory)
    target = Path(str(directory) + ".txt")
    if target.exists():
        raise FileExistsError("Text report already exists; use a new collection directory")
    summaries = ["PowerOps diagnostic collection", "", "Not a cloud-health or fencing acceptance test.", ""]
    sections = []
    partial = False
    api_names = ['api', 'api_after'] if require_final_api or (directory / 'api_after.json').exists() else ['api']
    for name in api_names + expected:
        if not HOST.fullmatch(name) or name in api_names and expected.count(name):
            raise ValueError("Invalid or reserved inventory hostname")
        path = directory / (name + ".json")
        if not path.exists() or path.is_symlink():
            summaries.append(name + ": MISSING")
            partial = True
            continue
        data = json.loads(path.read_text())
        report = data.get("report", {})
        decode_error = False
        if isinstance(report, str):
            try:
                report = json.loads(report)
            except (ValueError, TypeError):
                decode_error = True
                report = {"checks": [{"name": "collector_output", "status": "invalid_json",
                                       "output": report}], "logs": []}
        data["report"] = report
        data = sanitize(data)
        report = data["report"]
        transport = data.get("transport", {})
        category = error_kind(transport.get('msg', '') + '\n' + transport.get('stderr', ''))
        if category:
            transport['error_kind'] = category
        failures = []
        if transport.get("unreachable"):
            state = "UNREACHABLE"
        elif decode_error or transport.get("rc", 1) != 0 or not isinstance(report, dict) or not report:
            state = "COLLECTOR_ERROR"
        else:
            for row in report.get("checks", []) + report.get("logs", []):
                if row.get("status") != "ok" or row.get("truncated") or row.get("scan_truncated"):
                    failures.append("  - " + row.get("name", row.get("path", "unknown")) + ": " +
                                    row.get("status", "unknown") +
                                          (" (truncated)" if row.get("truncated") or row.get("scan_truncated") else "") +
                                          (' [' + row['error_kind'] + ']' if row.get('error_kind') else ''))
            state = "PARTIAL" if failures else "COLLECTED"
        partial |= state != "COLLECTED"
        summaries.extend([name + ": " + state] + failures + [""])
        if category:
            summaries.append('  transport_error: ' + category)
        if isinstance(report, dict):
            summaries.extend('  observation: ' + item for item in report.get('observations', []))
        sections += ["", "=" * 72, "HOST: " + name + " / " + state, "=" * 72,
                     "TRANSPORT: " + json.dumps(transport, ensure_ascii=False), ""]
        if isinstance(report, dict):
            sections.append(json.dumps({k: v for k, v in report.items() if k not in {"checks", "logs"}},
                                       ensure_ascii=False, indent=2))
            for row in report.get("checks", []) + report.get("logs", []):
                sections += ["", "--- " + row.get("name", row.get("path", "unknown")) + " ---",
                             json.dumps({k: v for k, v in row.items() if k != "output"}, ensure_ascii=False),
                             row.get("output", "")]
    status = "PARTIAL" if partial else "COLLECTED"
    summaries[2:2] = ["Collection status: " + status, ""]
    summaries += ["", "Log time filtering uses window.log_timezone for timestamps without offsets.",
                  "API snapshots are non-atomic current reads, not historical state or stable-off proof.",
                  "unparsed_time includes an explicitly unfiltered fallback. Truncation means incomplete evidence.",
                  "Typical secrets are masked, but this file remains confidential; review before sharing."]
    body = "\n".join(summaries + sections).encode()
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
    return dict(status=status, report=str(target), bytes=len(body))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["validate", "host", "api", "report"])
    parser.add_argument("--config", default="{}")
    parser.add_argument("--directory")
    parser.add_argument("--expected", default="[]")
    parser.add_argument("--previous")
    parser.add_argument("--require-final-api", action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.mode == "report":
            result = write_report(args.directory, json.loads(args.expected), args.require_final_api)
        else:
            config = validate_config(json.loads(args.config))
            if args.mode == "validate":
                result = config
            else:
                collector = Collector(config)
                result = collector.host() if args.mode == "host" else collector.api(previous=args.previous)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps(dict(error=redact(str(exc)), type=type(exc).__name__)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
