"""Bounded controller checks. No reused SSH session, shell, or supplied commands."""
import http.client
import ipaddress
import re
import socket
import ssl
import subprocess
from urllib.parse import urlsplit


def _port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError('INVALID_VERIFICATION_PORT')
    return value


def ssh_command(config):
    if config.get('connection') not in ('ssh', 'ansible.builtin.ssh'):
        raise ValueError('FRESH_SSH_REQUIRES_SSH_CONNECTION')
    if any(config.get(k) for k in ('ssh_common_args', 'ssh_extra_args', 'password')):
        raise ValueError('UNSUPPORTED_SSH_OPTIONS')
    host, user = config.get('host', ''), config.get('user', '')
    if not isinstance(host, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.:_-]*', host):
        raise ValueError('INVALID_SSH_HOST')
    if not isinstance(user, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.-]*', user):
        raise ValueError('EXPLICIT_SSH_USER_REQUIRED')
    argv = ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            '-o', 'ConnectionAttempts=1', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ServerAliveInterval=5',
            '-o', 'ServerAliveCountMax=1', '-p', str(_port(config.get('port'))), '-l', user]
    identity = config.get('identity')
    if identity:
        if not isinstance(identity, str) or not identity.startswith('/') or '\n' in identity:
            raise ValueError('INVALID_SSH_IDENTITY_PATH')
        argv.extend(['-o', 'IdentitiesOnly=yes', '-i', identity])
    return argv + [host, '/bin/true']


def validate_checks(checks):
    if not isinstance(checks, list) or not 1 <= len(checks) <= 16:
        raise ValueError('SERVICE_VERIFICATION_REQUIRED')
    ids = ['ssh-fresh']
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError('INVALID_VERIFICATION_CHECK')
        ident = check.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', ident) or ident in ids:
            raise ValueError('INVALID_VERIFICATION_ID')
        ids.append(ident)
        if check.get('type') == 'tcp' and set(check) == {'id', 'type', 'host', 'port'}:
            ip = ipaddress.ip_address(check['host'])
            if ip.is_unspecified or ip.is_multicast or ip.is_loopback or ip.is_link_local:
                raise ValueError('INVALID_VERIFICATION_ADDRESS')
            _port(check['port'])
        elif check.get('type') == 'http' and set(check) == {'id', 'type', 'url', 'status'}:
            url = urlsplit(check['url'])
            if (url.scheme not in ('http', 'https') or not url.hostname or url.username or
                    url.password or url.fragment or url.query or any(c.isspace() for c in check['url'])):
                raise ValueError('INVALID_VERIFICATION_URL')
            _port(url.port or (443 if url.scheme == 'https' else 80))
            if type(check['status']) is not int or not 200 <= check['status'] <= 299:
                raise ValueError('INVALID_VERIFICATION_STATUS')
        else:
            raise ValueError('INVALID_VERIFICATION_CHECK')
    return ids


def verify(config, checks, ssh_only=False):
    argv = ssh_command(config)
    ids = ['ssh-fresh'] if ssh_only else validate_checks(checks)
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=20, check=False)
        if result.returncode:
            raise ValueError('FRESH_SSH_FAILED')
        for check in ([] if ssh_only else checks):
            if check['type'] == 'tcp':
                with socket.create_connection((check['host'], check['port']), timeout=5):
                    pass
            else:
                url = urlsplit(check['url'])
                conn = (http.client.HTTPSConnection(url.hostname, url.port, timeout=5,
                                                   context=ssl.create_default_context())
                        if url.scheme == 'https' else
                        http.client.HTTPConnection(url.hostname, url.port, timeout=5))
                try:
                    conn.request('GET', url.path or '/')
                    response = conn.getresponse()
                    if response.status != check['status']:
                        raise ValueError('SERVICE_VERIFICATION_FAILED')
                finally:
                    conn.close()
    except (OSError, subprocess.TimeoutExpired, http.client.HTTPException):
        raise ValueError('CONNECTIVITY_VERIFICATION_FAILED') from None
    return ids
