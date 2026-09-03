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
]
