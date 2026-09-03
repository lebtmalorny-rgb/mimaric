from openstack_dashboard.test.settings import *  # noqa: F403,H303


INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
INSTALLED_APPS.append('poweropsdashboard')

ROOT_URLCONF = 'poweropsdashboard.test.urls'

POWEROPS_REGION_NAME = 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES = ['ops-project']
POWEROPS_ALLOWED_USER_NAMES = ['ops-user']
POWEROPS_MOCK_MODE = False
