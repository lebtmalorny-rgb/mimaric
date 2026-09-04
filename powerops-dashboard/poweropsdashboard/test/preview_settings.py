from openstack_dashboard import theme_settings

from poweropsdashboard.test.settings import *  # noqa: F403,H303


DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
AVAILABLE_REGIONS = [
    ('http://localhost/identity/v3', 'RegionOne'),
]
POWEROPS_MOCK_MODE = True
POWEROPS_REGION_NAME = 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES = ['ops-project']
POWEROPS_ALLOWED_USER_NAMES = ['ops-user']

COMPRESS_PRECOMPILERS = (
    ('text/scss', 'horizon.utils.scss_filter.ScssFilter'),
)

STATICFILES_DIRS = list(STATICFILES_DIRS)  # noqa: F405
STATICFILES_DIRS.extend(theme_settings.get_theme_static_dirs(
    AVAILABLE_THEMES, THEME_COLLECTION_DIR, ROOT_PATH))  # noqa: F405

MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.append(
    'poweropsdashboard.test.preview_middleware.PreviewUserMiddleware')
