from ansible.module_utils.basic import AnsibleModule
import json
import os

module = AnsibleModule(argument_spec={
    'action': {'type': 'str'}, 'txid': {'type': 'str', 'default': ''},
}, supports_check_mode=True)
if module.check_mode:
    module.exit_json(changed=False)
with open(os.environ['POWEROPS_TEST_MUTATION_MARKER'], 'a') as stream:
    stream.write(json.dumps(module.params) + '\n')
if os.environ.get('POWEROPS_TEST_MUTATION_FAIL'):
    module.fail_json(msg='injected OS failure', changed=False)
module.exit_json(changed=True, state='ROLLED_BACK')
