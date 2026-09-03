from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse

from horizon import views

from poweropsdashboard import api
from poweropsdashboard import auth
from poweropsdashboard import exceptions
from poweropsdashboard.hosts import tables
from poweropsdashboard import presentation


class ProtectedViewMixin:

    def dispatch(self, request, *args, **kwargs):
        self.authorization = auth.authorize_user(request.user)
        return super().dispatch(request, *args, **kwargs)


class IndexView(ProtectedViewMixin, views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/index.html'
    page_title = 'Compute Hosts'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['region_name'] = settings.POWEROPS_REGION_NAME
        context['inventory_error'] = None
        context['inventory_verified'] = False
        rows = ()
        active_executions = {}

        try:
            client = api.get_client(self.request)
            executions = client.list_executions(
                all_projects=self.authorization.is_admin)
            parsed_rows = presentation.latest_successful_inventory(
                executions)
            if parsed_rows is None:
                context['inventory_error'] = (
                    'No verified inventory snapshot is available'
                )
            else:
                rows = parsed_rows
                active_executions = presentation.match_active_executions(
                    executions)
                context['inventory_verified'] = True
        except Exception:
            context['inventory_error'] = (
                'Verified PowerOps inventory is unavailable'
            )

        table = tables.ComputeHostsTable(self.request, data=rows)
        table.active_executions = active_executions
        context['table'] = table
        return context


class RefreshInventoryView(ProtectedViewMixin,
                           views.HorizonTemplateView):

    def get(self, request, *args, **kwargs):
        try:
            execution = api.get_client(request).start_inventory()
            execution_id = presentation.execution_id(execution)
        except Exception:
            return HttpResponse(
                'PowerOps inventory refresh is unavailable', status=503)
        return redirect(reverse(
            'horizon:powerops:compute_hosts:execution',
            args=(execution_id,),
        ))


class ExecutionView(ProtectedViewMixin, views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/execution.html'
    page_title = 'PowerOps Execution'

    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except exceptions.InvalidBackendData:
            return HttpResponse(
                'PowerOps execution data failed validation', status=502)
        except Exception:
            return HttpResponse(
                'PowerOps execution state is unavailable', status=503)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        execution_id = self.kwargs['execution_id']
        client = api.get_client(self.request)
        execution = client.get_execution(execution_id)
        tasks = client.list_tasks(execution_id)
        execution_state = presentation.parse_execution_state(execution)
        if execution_state.id != execution_id:
            raise exceptions.InvalidBackendData(
                'Execution identifier does not match the requested resource'
            )
        context['execution'] = execution_state
        context['tasks'] = presentation.parse_tasks(tasks)
        return context
