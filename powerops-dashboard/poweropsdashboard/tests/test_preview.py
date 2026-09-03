import re
from types import SimpleNamespace
from unittest import mock

from django.test import override_settings
from django.test import SimpleTestCase

from poweropsdashboard import api
from poweropsdashboard import mock_data
from poweropsdashboard.test.preview_middleware import PreviewUserMiddleware
from poweropsdashboard.test import preview_settings


def _user():
    return SimpleNamespace(
        roles=[{'name': 'powerops_operator'}],
        project_name='ops-project',
        username='ops-user',
        project_id='project-id',
        services_region='RegionOne',
        is_authenticated=True,
        has_perms=lambda permissions: True,
    )


def _token(response):
    content = response.content.decode('utf-8')
    match = re.search(
        r'name="submission_token"[^>]*value="([^"]+)"', content)
    if match is None:
        match = re.search(
            r'value="([^"]+)"[^>]*name="submission_token"', content)
    if match is None:
        raise AssertionError('submission token was not rendered')
    return match.group(1)


class PreviewSettingsTests(SimpleTestCase):

    def test_preview_is_debug_local_mock_only(self):
        self.assertIs(True, preview_settings.DEBUG)
        self.assertEqual(
            ['127.0.0.1', 'localhost'], preview_settings.ALLOWED_HOSTS)
        self.assertIs(True, preview_settings.POWEROPS_MOCK_MODE)
        self.assertEqual('RegionOne', preview_settings.POWEROPS_REGION_NAME)
        self.assertEqual(
            ['ops-project'],
            preview_settings.POWEROPS_ALLOWED_PROJECT_NAMES,
        )
        self.assertEqual(
            ['ops-user'], preview_settings.POWEROPS_ALLOWED_USER_NAMES)

    def test_preview_middleware_rejects_nonlocal_and_sets_fake_user_locally(
            self):
        downstream = mock.Mock(return_value='ok')
        middleware = PreviewUserMiddleware(downstream)
        local = SimpleNamespace(META={'REMOTE_ADDR': '127.0.0.1'})
        remote = SimpleNamespace(META={'REMOTE_ADDR': '192.0.2.10'})

        self.assertEqual('ok', middleware(local))
        self.assertEqual('ops-user', local.user.username)
        self.assertEqual([], local.user.authorized_tenants)
        self.assertFalse(hasattr(local.user, 'token'))
        self.assertEqual(403, middleware(remote).status_code)


class PreviewFixtureTests(SimpleTestCase):

    def test_fixtures_cover_required_states_without_secrets(self):
        rows = mock_data.HOST_ROWS
        operable = [row for row in rows if row['operable']]
        blocked = [row for row in rows if not row['operable']]
        self.assertTrue(any(
            row['power_state'] == 'power on'
            and len({vm['project_id'] for vm in row['instances']}) == 2
            for row in operable
        ))
        self.assertTrue(any(
            row['blocking_reason'] == 'ambiguous_masakari_host'
            for row in blocked
        ))
        self.assertTrue(any(
            item['workflow_name'] == 'power_ops.planned_power_off'
            and item['state'] == 'RUNNING'
            for item in mock_data.EXECUTIONS
        ))
        paused = next(
            item for item in mock_data.EXECUTIONS
            if item['workflow_name'] == 'power_ops.power_on_and_return'
            and item['state'] == 'PAUSED'
        )
        self.assertEqual('PAUSED', paused['state'])
        self.assertEqual(
            'operator_inspection_gate',
            mock_data.TASKS[paused['id']][0]['name'],
        )
        self.assertTrue(any(
            item['state'] == 'ERROR'
            and item.get('verification_required') is True
            for item in mock_data.EXECUTIONS
        ))

        dumped = repr((rows, mock_data.EXECUTIONS, mock_data.TASKS)).lower()
        for forbidden in (
                'password', 'service_catalog', 'bmc_address', 'driver_info'):
            self.assertNotIn(forbidden, dumped)

    def test_mock_reads_are_always_fresh_defensive_copies(self):
        client = api.MockPowerOpsClient()
        first = client.list_executions(all_projects=True)
        first[0]['state'] = 'CORRUPTED'
        first_status = client.start_host_status(
            mock_data.RETURN_HOST, mock_data.RETURN_SEGMENT_UUID)
        first_status['output']['result']['host'] = 'CORRUPTED'

        second = client.list_executions(all_projects=True)
        second_status = client.start_host_status(
            mock_data.RETURN_HOST, mock_data.RETURN_SEGMENT_UUID)

        self.assertNotEqual('CORRUPTED', second[0]['state'])
        self.assertEqual(
            mock_data.RETURN_HOST,
            second_status['output']['result']['host'],
        )


@override_settings(POWEROPS_MOCK_MODE=True)
class PreviewPageTests(SimpleTestCase):

    @mock.patch.object(api.mistral_client, 'client')
    @mock.patch.object(api.base, 'url_for')
    def test_all_preview_pages_render_without_network(
            self, url_for, client_factory):
        urls = [
            '/powerops/',
            '/powerops/executions/{}/'.format(
                mock_data.PLANNED_EXECUTION_UUID),
            '/powerops/executions/{}/'.format(
                mock_data.ERROR_EXECUTION_UUID),
            '/powerops/planned/power_off/{}/{}/'.format(
                mock_data.ACTION_SEGMENT_UUID, mock_data.ACTION_HOST),
            '/powerops/return/start/{}/'.format(
                mock_data.SOURCE_EXECUTION_UUID),
            '/powerops/return/resume/{}/'.format(
                mock_data.RETURN_EXECUTION_UUID),
        ]

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            responses = [self.client.get(url) for url in urls]

        self.assertTrue(all(response.status_code == 200
                            for response in responses))
        url_for.assert_not_called()
        client_factory.assert_not_called()

    @mock.patch.object(api.mistral_client, 'client')
    @mock.patch.object(api.base, 'url_for')
    def test_every_mock_mutation_post_returns_conflict(
            self, url_for, client_factory):
        planned_url = '/powerops/planned/power_off/{}/{}/'.format(
            mock_data.ACTION_SEGMENT_UUID, mock_data.ACTION_HOST)
        start_url = '/powerops/return/start/{}/'.format(
            mock_data.SOURCE_EXECUTION_UUID)
        resume_url = '/powerops/return/resume/{}/'.format(
            mock_data.RETURN_EXECUTION_UUID)

        with mock.patch(
                'django.contrib.auth.middleware.auth.get_user',
                return_value=_user()):
            planned_token = _token(self.client.get(planned_url))
            planned = self.client.post(planned_url, {
                'typed_host': mock_data.ACTION_HOST,
                'instance_policy': 'require_empty',
                'submission_token': planned_token,
            })
            start_token = _token(self.client.get(start_url))
            start = self.client.post(start_url, {
                'submission_token': start_token,
            })
            resume_token = _token(self.client.get(resume_url))
            resume = self.client.post(resume_url, {
                'submission_token': resume_token,
                'stale_domains_checked': 'on',
            })

        self.assertEqual([409, 409, 409], [
            planned.status_code, start.status_code, resume.status_code])
        url_for.assert_not_called()
        client_factory.assert_not_called()
