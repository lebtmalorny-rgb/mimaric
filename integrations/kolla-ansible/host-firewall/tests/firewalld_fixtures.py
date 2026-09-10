"""Literal Linux command responses; only the external OS boundary is faked."""


def command(stdout='', rc=0, stderr='', **changes):
    result = {'argv': [], 'rc': rc, 'stdout': stdout, 'stderr': stderr,
              'available': True, 'truncated': False, 'timed_out': False}
    result.update(changes)
    return result


def installed_firewalld():
    return {
        'firewalld_package': command('firewalld\t1.3.4\t18.sl9_7^1\tnoarch\n'),
        'firewalld_python_package': command('python3-firewall\t1.3.4\t18.sl9_7^1\tnoarch\n'),
        'firewalld_version': command('1.3.4\n'),
        'firewalld_service': command(
            'Id=firewalld.service\nLoadState=loaded\nActiveState=active\n'
            'SubState=running\nUnitFileState=enabled\n'),
        'firewalld_state': command('running\n'),
        'firewalld_runtime_policies': command(),
        'firewalld_permanent_policies': command(),
    }
