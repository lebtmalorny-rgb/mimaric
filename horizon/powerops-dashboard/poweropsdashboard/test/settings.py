from openstack_dashboard.test.settings import *  # noqa: F403,H303


INSTALLED_APPS = [  # noqa: F405
    app for app in INSTALLED_APPS  # noqa: F405
    if (not app.startswith('openstack_dashboard.dashboards.')
        or app == 'openstack_dashboard.dashboards.settings')
]
INSTALLED_APPS.append('poweropsdashboard')
INSTALLED_APPS.append('poweropsdashboard.hosts')

ROOT_URLCONF = 'poweropsdashboard.test.urls'
SESSION_REFRESH = False
HORIZON_CONFIG = dict(HORIZON_CONFIG)  # noqa: F405
HORIZON_CONFIG['dashboards'] = ('powerops', 'settings')
HORIZON_CONFIG['default_dashboard'] = 'powerops'
HORIZON_CONFIG['angular_modules'] = []
HORIZON_CONFIG['external_templates'] = []
HORIZON_CONFIG['header_sections'] = []
HORIZON_CONFIG['js_files'] = []
HORIZON_CONFIG['js_spec_files'] = []
HORIZON_CONFIG['panel_customization'] = []
HORIZON_CONFIG['scss_files'] = []

POWEROPS_REGION_NAME = 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES = ['ops-project']
POWEROPS_ALLOWED_USER_NAMES = ['ops-user']
POWEROPS_MOCK_MODE = False
