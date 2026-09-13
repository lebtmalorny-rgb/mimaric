"""Identical oslo.config options for both consumers and the operator CLI."""
from oslo_config import cfg

from .guard import Guard, MAX_PARALLEL, bounded
from .etcd import number

GROUP = 'powerops_evacuation_guard'
OPTS = [
    cfg.BoolOpt('enabled', default=False, help='Enable durable receiving-compute evacuation admission.'),
    cfg.StrOpt('endpoint', default='http://127.0.0.1:2379', help='etcd v3 gateway; no URL credentials.'),
    cfg.StrOpt('prefix', default='/powerops/evacuation/v1', help='Shared durable evacuation namespace.'),
    cfg.FloatOpt('timeout', default=5.0, help='Finite positive HTTP timeout in seconds.'),
    cfg.IntOpt('max_parallel', default=3, min=1, max=MAX_PARALLEL, help='Shared admitted evacuation limit.'),
    cfg.FloatOpt('cooldown', default=5.0, help='Finite nonnegative full per-target cooldown.'),
    cfg.FloatOpt('admission_timeout', default=3600.0, help='Finite positive receiving-compute waiting deadline.'),
    cfg.FloatOpt('poll_interval', default=1.0, help='Finite positive admission polling interval.'),
    cfg.IntOpt('submission_workers', default=3, min=1, max=MAX_PARALLEL, help='Process-wide Masakari submission concurrency.'),
    cfg.StrOpt('ca_file', default=None, help='CA bundle, or system trust when unset.'),
    cfg.StrOpt('cert_file', default=None, help='Optional PEM client certificate paired with key_file.'),
    cfg.StrOpt('key_file', default=None, help='Optional PEM client key paired with cert_file.'),
]


def register_opts(conf):
    conf.register_opts(OPTS, group=GROUP)


def list_opts():
    return [(GROUP, list(OPTS))]


def from_conf(conf):
    """Validate every setting; callers apply the disabled/enabled switch."""
    opt = conf[GROUP]
    bounded(opt.submission_workers, 'submission_workers')
    number(opt.admission_timeout, 'admission_timeout', strict=True)
    number(opt.poll_interval, 'poll_interval', strict=True)
    return Guard(opt.endpoint, prefix=opt.prefix, timeout=opt.timeout,
                 ca_file=opt.ca_file, cert_file=opt.cert_file, key_file=opt.key_file,
                 max_parallel=opt.max_parallel, cooldown=opt.cooldown)
