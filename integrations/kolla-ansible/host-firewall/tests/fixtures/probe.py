"""Test-only OS boundary, not shipped in the ansible/ overlay."""
import json
import os
from ansible.module_utils.basic import AnsibleModule

module = AnsibleModule(argument_spec={
    'timeout': {'type': 'int'}, 'max_bytes': {'type': 'int'},
}, supports_check_mode=True)
marker = os.environ['POWEROPS_TEST_PROBE_MARKER']
with open(marker, 'a') as stream:
    stream.write('probe\n')
observation = {'timestamp': '2026-09-10T10:00:00+00:00', 'commands': {
    'addresses': {'argv': ['ip', '-j', 'address', 'show'], 'rc': 0,
                  'available': True, 'truncated': False, 'timed_out': False,
                  'stderr': '', 'stdout': json.dumps([{'ifname': 'ethapi', 'addr_info': [
                      {'family': 'inet', 'local': '192.0.2.2', 'scope': 'global'},
                      {'family': 'inet', 'local': '192.0.2.3', 'scope': 'global'},
                  ]}])},
    'nft': {'argv': ['nft', '-j', 'list', 'ruleset'], 'rc': 0,
            'available': True, 'truncated': False, 'timed_out': False,
            'stderr': '', 'stdout': '{"nftables": []}'},
}}
module.exit_json(changed=False, snapshot=observation)
