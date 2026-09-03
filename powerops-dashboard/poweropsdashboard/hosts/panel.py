from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

import horizon

from poweropsdashboard import auth
from poweropsdashboard import dashboard


class ComputeHosts(horizon.Panel):
    name = _('Compute Hosts')
    slug = 'compute_hosts'

    def allowed(self, context):
        try:
            auth.authorize_user(context['request'].user)
        except PermissionDenied:
            return False
        return True


dashboard.PowerOps.register(ComputeHosts)
