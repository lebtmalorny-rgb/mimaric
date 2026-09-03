from django.utils.translation import gettext_lazy as _

import horizon


class PowerOps(horizon.Dashboard):
    name = _('PowerOps')
    slug = 'powerops'
    default_panel = 'compute_hosts'


horizon.register(PowerOps)
