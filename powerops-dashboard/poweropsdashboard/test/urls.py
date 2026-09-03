from django.conf.urls import include
from django.urls import re_path

import horizon
import horizon.base


urlpatterns = [
    re_path(r'', horizon.base._wrapped_include(horizon.urls)),
    re_path(r'^auth/', include('django.contrib.auth.urls')),
]
