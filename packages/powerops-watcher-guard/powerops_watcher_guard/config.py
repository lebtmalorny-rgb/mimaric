"""Shared oslo.config options for Masakari, Watcher and operator commands."""
from oslo_config import cfg

from powerops_watcher_guard.gate import Gate


GROUP = 'watcher_automation_guard'
OPTS = [
    cfg.BoolOpt('enabled', default=False,
                help='Enforce the shared scheduled Watcher automation guard.'),
    cfg.StrOpt('endpoint', default='http://127.0.0.1:2379',
               help='Single etcd v3 gateway or HA endpoint; no URL credentials.'),
    cfg.StrOpt('prefix', default='/powerops/watcher-automation/v1',
               help='Persistent etcd namespace shared by Masakari and Watcher.'),
    cfg.FloatOpt('timeout', default=5.0,
                 help='Positive HTTP connect/read timeout in seconds.'),
    cfg.StrOpt('ca_file', default=None, help='CA bundle; system trust is used if unset.'),
    cfg.StrOpt('cert_file', default=None, help='Optional PEM client certificate.'),
    cfg.StrOpt('key_file', default=None, help='Optional PEM client certificate key.'),
]


def register_opts(conf):
    conf.register_opts(OPTS, group=GROUP)


def list_opts():
    return [(GROUP, list(OPTS))]


def from_conf(conf):
    """Construct a gate. Service callers decide whether enabled applies."""
    options = conf[GROUP]
    return Gate(options.endpoint, prefix=options.prefix, timeout=options.timeout,
                ca_file=options.ca_file, cert_file=options.cert_file, key_file=options.key_file)
