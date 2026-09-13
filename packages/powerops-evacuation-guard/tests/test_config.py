import pytest
from oslo_config import cfg
from powerops_evacuation_guard import GuardDenied


def test_defaults_construct_guard_without_enabling_it():
    from powerops_evacuation_guard import config
    conf = cfg.ConfigOpts()
    config.register_opts(conf)
    g = config.from_conf(conf)
    assert not conf.powerops_evacuation_guard.enabled
    assert g.max_parallel == 3
    assert g.cooldown == 5
    assert conf.powerops_evacuation_guard.submission_workers == 3
    assert conf.powerops_evacuation_guard.admission_timeout == 3600
    assert conf.powerops_evacuation_guard.poll_interval == 1


@pytest.mark.parametrize('option,value', [
    ('max_parallel', 0), ('max_parallel', 1025), ('submission_workers', 0),
    ('submission_workers', 1025), ('timeout', float('inf')), ('cooldown', float('nan')),
    ('admission_timeout', 0), ('admission_timeout', float('nan')),
    ('poll_interval', -1), ('poll_interval', float('inf'))])
def test_invalid_config_is_rejected_before_runtime(option, value):
    from powerops_evacuation_guard import config
    conf = cfg.ConfigOpts()
    config.register_opts(conf)
    with pytest.raises((GuardDenied, ValueError)):
        conf.set_override(option, value, group=config.GROUP)
        config.from_conf(conf)
