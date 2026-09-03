import collections

from django.conf import settings

from poweropsdashboard.exceptions import PermissionDenied


Authorization = collections.namedtuple(
    'Authorization', ['branch', 'is_admin']
)


def authorize_user(user):
    raw_roles = getattr(user, 'roles', None)
    if not isinstance(raw_roles, (list, tuple)):
        raise PermissionDenied

    roles = []
    for role in raw_roles:
        if not isinstance(role, dict):
            raise PermissionDenied
        name = role.get('name')
        if not isinstance(name, str):
            raise PermissionDenied
        roles.append(name)

    if 'admin' in roles:
        return Authorization('admin', True)
    if ('powerops_operator' in roles
            and user.project_name
            in settings.POWEROPS_ALLOWED_PROJECT_NAMES
            and user.username in settings.POWEROPS_ALLOWED_USER_NAMES):
        return Authorization('powerops_operator', False)
    raise PermissionDenied
