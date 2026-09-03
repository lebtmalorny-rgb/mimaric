from poweropsdashboard.test.settings import *  # noqa: F403,H303


DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
POWEROPS_MOCK_MODE = True
POWEROPS_REGION_NAME = 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES = ['ops-project']
POWEROPS_ALLOWED_USER_NAMES = ['ops-user']

MIDDLEWARE = list(MIDDLEWARE)  # noqa: F405
MIDDLEWARE.append(
    'poweropsdashboard.test.preview_middleware.PreviewUserMiddleware')
