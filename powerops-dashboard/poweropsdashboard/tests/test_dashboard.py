import collections
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

import horizon
from mistralclient.api import client as mistral_client

from poweropsdashboard import dashboard


User = collections.namedtuple(
    'User', ['roles', 'project_name', 'username', 'is_authenticated'])


class DashboardRegistrationTests(SimpleTestCase):

    def test_registers_standalone_dashboard_and_compute_hosts_panel(self):
        registered_dashboard = horizon.get_dashboard('powerops')
        registered_dashboard._autodiscover()
        registered_panel = registered_dashboard.get_panel('compute_hosts')

        self.assertIsInstance(registered_dashboard, dashboard.PowerOps)
        self.assertIsNotNone(registered_panel)
        self.assertEqual(
            'poweropsdashboard.hosts.panel',
            registered_panel.__class__.__module__,
        )
        self.assertEqual('compute_hosts', registered_panel.slug)
        self.assertEqual(
            '/powerops/', registered_dashboard.get_absolute_url())
        self.assertEqual(
            '/powerops/',
            reverse('horizon:powerops:compute_hosts:index'),
        )

    def test_panel_visibility_uses_the_same_authorization_predicate(self):
        registered_dashboard = horizon.get_dashboard('powerops')
        registered_dashboard._autodiscover()
        compute_hosts = registered_dashboard.get_panel('compute_hosts')
        allowed_user = User(
            roles=[{'name': 'powerops_operator'}],
            project_name='ops-project',
            username='ops-user',
            is_authenticated=True,
        )
        denied_user = allowed_user._replace(username='wrong-user')

        self.assertTrue(compute_hosts.allowed({
            'request': mock.Mock(user=allowed_user),
        }))
        self.assertFalse(compute_hosts.allowed({
            'request': mock.Mock(user=denied_user),
        }))


class DirectURLAuthorizationTests(SimpleTestCase):

    @mock.patch.object(mistral_client, 'client')
    def test_unauthorized_get_returns_403_before_mistral_client(
            self, client_factory):
        user = User(
            roles=[{'name': 'powerops_operator'}],
            project_name='ops-project',
            username='wrong-user',
            is_authenticated=True,
        )
        with mock.patch('django.contrib.auth.middleware.auth.get_user',
                        return_value=user):
            response = self.client.get('/powerops/')

        self.assertEqual(403, response.status_code)
        client_factory.assert_not_called()
