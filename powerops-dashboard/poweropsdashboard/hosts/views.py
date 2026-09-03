from django.http import HttpResponse

from horizon import views

from poweropsdashboard import auth


class IndexView(views.HorizonTemplateView):
    template_name = 'powerops/compute_hosts/index.html'
    page_title = 'Compute Hosts'

    def dispatch(self, request, *args, **kwargs):
        auth.authorize_user(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return HttpResponse()
