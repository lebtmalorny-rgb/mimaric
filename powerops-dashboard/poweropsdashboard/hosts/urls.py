from django.urls import re_path

from poweropsdashboard.hosts import views


urlpatterns = [
    re_path(r'^$', views.IndexView.as_view(), name='index'),
    re_path(
        r'^refresh/$',
        views.RefreshInventoryView.as_view(),
        name='refresh_inventory',
    ),
    re_path(
        r'^executions/(?P<execution_id>'
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$',
        views.ExecutionView.as_view(),
        name='execution',
    ),
    re_path(
        r'^planned/(?P<operation>power_off|reboot)/'
        r'(?P<segment_uuid>'
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/'
        r'(?P<host>[A-Za-z0-9][A-Za-z0-9._-]*)/$',
        views.PlannedOperationView.as_view(),
        name='planned',
    ),
]
