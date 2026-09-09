from django.test import SimpleTestCase

from poweropsdashboard import auth
from poweropsdashboard.hosts import forms
from poweropsdashboard import presentation


SEGMENT_UUID = '11111111-1111-1111-1111-111111111111'
NODE_UUID = '22222222-2222-2222-2222-222222222222'


def _host_row():
    return presentation.HostRow(
        region_name='RegionOne',
        segment_uuid=SEGMENT_UUID,
        host='compute-01',
        ironic_node_uuid=NODE_UUID,
        power_state='power on',
        target_power_state=None,
        nova_status='enabled',
        nova_state='up',
        masakari_maintenance=False,
        instance_count=0,
        instances=(),
        operable=True,
        blocking_reason=None,
    )


def _data(**overrides):
    result = {
        'typed_host': 'compute-01',
        'instance_policy': 'require_empty',
        'submission_token': 'one-use-token',
    }
    result.update(overrides)
    return result


class PlannedOperationFormTests(SimpleTestCase):

    def setUp(self):
        self.admin = auth.Authorization('admin', True)
        self.operator = auth.Authorization('powerops_operator', False)
        self.host_row = _host_row()

    def test_policies_are_closed_and_require_empty_is_default(self):
        form = forms.PlannedOperationForm(
            self.operator, self.host_row, 'power_off')

        self.assertEqual(
            ('require_empty', 'live_migrate', 'stop'),
            tuple(value for value, _label
                  in form.fields['instance_policy'].choices),
        )
        self.assertEqual(
            'require_empty', form.fields['instance_policy'].initial)

        for policy in ('require_empty', 'live_migrate', 'stop'):
            with self.subTest(policy=policy):
                bound = forms.PlannedOperationForm(
                    self.operator,
                    self.host_row,
                    'power_off',
                    data=_data(instance_policy=policy),
                )
                self.assertTrue(bound.is_valid(), bound.errors)
                self.assertEqual({
                    'host': 'compute-01',
                    'segment_uuid': SEGMENT_UUID,
                    'instance_policy': policy,
                    'allow_hard_off': False,
                }, bound.workflow_input())
                self.assertIs(
                    bool, type(bound.workflow_input()['allow_hard_off']))

        unknown = forms.PlannedOperationForm(
            self.operator,
            self.host_row,
            'power_off',
            data=_data(instance_policy='delete'),
        )
        self.assertFalse(unknown.is_valid())
        self.assertIn('instance_policy', unknown.errors)

    def test_typed_host_must_match_byte_for_byte(self):
        for typed_host in (' compute-01', 'compute-01 ', 'COMPUTE-01'):
            with self.subTest(typed_host=typed_host):
                form = forms.PlannedOperationForm(
                    self.operator,
                    self.host_row,
                    'power_off',
                    data=_data(typed_host=typed_host),
                )
                self.assertFalse(form.is_valid())
                self.assertIn('typed_host', form.errors)

    def test_admin_power_off_requires_separate_hard_off_confirmation(self):
        unbound = forms.PlannedOperationForm(
            self.admin, self.host_row, 'power_off')
        self.assertIn('allow_hard_off', unbound.fields)
        self.assertIn('confirm_hard_off', unbound.fields)

        missing_confirmation = forms.PlannedOperationForm(
            self.admin,
            self.host_row,
            'power_off',
            data=_data(allow_hard_off='on'),
        )
        self.assertFalse(missing_confirmation.is_valid())
        self.assertIn('confirm_hard_off', missing_confirmation.errors)

        valid = forms.PlannedOperationForm(
            self.admin,
            self.host_row,
            'power_off',
            data=_data(allow_hard_off='on', confirm_hard_off='on'),
        )
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertIs(True, valid.workflow_input()['allow_hard_off'])

    def test_admin_cannot_confirm_hard_off_without_selecting_it(self):
        form = forms.PlannedOperationForm(
            self.admin,
            self.host_row,
            'power_off',
            data=_data(confirm_hard_off='on'),
        )

        self.assertFalse(form.is_valid())
        self.assertIn('confirm_hard_off', form.errors)

    def test_operator_has_no_hard_off_controls_and_forgery_is_rejected(self):
        unbound = forms.PlannedOperationForm(
            self.operator, self.host_row, 'power_off')
        self.assertNotIn('allow_hard_off', unbound.fields)
        self.assertNotIn('confirm_hard_off', unbound.fields)

        for forged_key in ('allow_hard_off', 'confirm_hard_off'):
            with self.subTest(forged_key=forged_key):
                form = forms.PlannedOperationForm(
                    self.operator,
                    self.host_row,
                    'power_off',
                    data=_data(**{forged_key: 'on'}),
                )
                self.assertFalse(form.is_valid())

    def test_reboot_never_exposes_or_accepts_hard_off(self):
        for authorization in (self.admin, self.operator):
            with self.subTest(authorization=authorization):
                unbound = forms.PlannedOperationForm(
                    authorization, self.host_row, 'reboot')
                self.assertNotIn('allow_hard_off', unbound.fields)
                self.assertNotIn('confirm_hard_off', unbound.fields)

                valid = forms.PlannedOperationForm(
                    authorization,
                    self.host_row,
                    'reboot',
                    data=_data(),
                )
                self.assertTrue(valid.is_valid(), valid.errors)
                self.assertIs(False, valid.workflow_input()[
                    'allow_hard_off'])

                for forged_key in ('allow_hard_off',
                                   'confirm_hard_off'):
                    forged = forms.PlannedOperationForm(
                        authorization,
                        self.host_row,
                        'reboot',
                        data=_data(**{forged_key: 'on'}),
                    )
                    self.assertFalse(forged.is_valid())

    def test_unknown_or_duplicate_browser_keys_are_rejected(self):
        unknown = forms.PlannedOperationForm(
            self.operator,
            self.host_row,
            'power_off',
            data=_data(host='forged-host'),
        )
        self.assertFalse(unknown.is_valid())

        duplicate_data = {
            'typed_host': ['compute-01', 'compute-02'],
            'instance_policy': ['require_empty'],
            'submission_token': ['one-use-token'],
        }
        duplicate = forms.PlannedOperationForm(
            self.operator,
            self.host_row,
            'power_off',
            data=duplicate_data,
        )
        self.assertFalse(duplicate.is_valid())
