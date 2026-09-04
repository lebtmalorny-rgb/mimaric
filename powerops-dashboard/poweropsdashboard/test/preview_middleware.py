from types import SimpleNamespace

from django.http import HttpResponseForbidden


_LOCAL_ADDRESSES = frozenset({'127.0.0.1', '::1'})


class PreviewUserMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.META.get('REMOTE_ADDR') not in _LOCAL_ADDRESSES:
            return HttpResponseForbidden()
        request.user = SimpleNamespace(
            id='preview-user-id',
            username='ops-user',
            project_id='preview-project-id',
            project_name='ops-project',
            roles=[{'name': 'powerops_operator'}],
            authorized_tenants=[],
            services_region='RegionOne',
            available_services_regions=['RegionOne'],
            user_domain_name='Default',
            system_scoped=False,
            is_system_user=False,
            is_authenticated=True,
            has_perms=lambda permissions: True,
        )
        return self.get_response(request)
