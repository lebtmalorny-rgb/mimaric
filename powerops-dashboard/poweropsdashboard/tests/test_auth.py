import collections
import unittest

from django.core.exceptions import PermissionDenied

from poweropsdashboard import auth


User = collections.namedtuple(
    'User', ['roles', 'project_name', 'username'])


class AuthorizeUserTests(unittest.TestCase):

    def test_exact_role_project_and_username_matrix(self):
        cases = (
            (['admin'], 'any-project', 'any-user', 'admin'),
            (['powerops_operator'], 'ops-project', 'ops-user',
             'powerops_operator'),
            (['powerops_operator'], 'wrong-project', 'ops-user', None),
            (['powerops_operator'], 'ops-project', 'wrong-user', None),
            (['member'], 'ops-project', 'ops-user', None),
            (['Admin'], 'ops-project', 'ops-user', None),
        )

        for role_names, project_name, username, expected_branch in cases:
            roles = [{'name': name} for name in role_names]
            user = User(roles, project_name, username)
            with self.subTest(role_names=role_names,
                              project_name=project_name,
                              username=username):
                if expected_branch is None:
                    with self.assertRaises(PermissionDenied):
                        auth.authorize_user(user)
                else:
                    authorization = auth.authorize_user(user)
                    self.assertEqual(expected_branch, authorization.branch)
                    self.assertEqual(expected_branch == 'admin',
                                     authorization.is_admin)

    def test_admin_branch_wins_for_dual_role_user(self):
        user = User(
            roles=[{'name': 'powerops_operator'}, {'name': 'admin'}],
            project_name='ops-project',
            username='ops-user',
        )

        self.assertEqual(
            auth.Authorization('admin', True),
            auth.authorize_user(user),
        )

    def test_malformed_role_containers_and_entries_are_denied(self):
        malformed_roles = (
            None,
            {'name': 'admin'},
            'admin',
            [{'name': 'admin'}, None],
            [{'name': 'admin'}, 'powerops_operator'],
            [{'name': 'admin'}, {}],
            [{'name': 'admin'}, {'name': None}],
            [{'name': 'admin'}, {'name': 1}],
        )

        for roles in malformed_roles:
            with self.subTest(roles=roles):
                with self.assertRaises(PermissionDenied):
                    auth.authorize_user(User(roles, 'ops-project', 'ops-user'))
