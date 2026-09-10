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
with open(os.environ['POWEROPS_TEST_OBSERVATION']) as stream:
    observation = json.load(stream)
module.exit_json(changed=False, snapshot=observation)
