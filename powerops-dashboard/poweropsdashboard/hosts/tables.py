from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from horizon import tables

from poweropsdashboard import constants


POWER_STATUS_CHOICES = (
    ('power on', True),
    ('power off', False),
)
NOVA_STATUS_CHOICES = (
    ('enabled', True),
    ('disabled', False),
)
NOVA_STATE_CHOICES = (
    ('up', True),
    ('down', False),
)


def instance_summary(host_row):
    return ', '.join(
        '{} ({}; {}; {})'.format(
            instance.name,
            instance.id,
            instance.project_id,
            instance.status,
        )
        for instance in host_row.instances
    ) or '-'


def maintenance_status(host_row):
    if host_row.masakari_maintenance is None:
        return 'unknown'
    return 'maintenance' if host_row.masakari_maintenance else 'normal'


def blocking_reason(host_row):
    if host_row.operable:
        return '-'
    return constants.BLOCKING_REASON_MESSAGES[host_row.blocking_reason]


class ActiveExecutionColumn(tables.Column):

    def get_raw_data(self, datum):
        active = getattr(self.table, 'active_executions', {})
        execution = active.get((datum.host, datum.segment_uuid))
        return execution.id if execution else None

    def get_link_url(self, datum):
        execution_id = self.get_raw_data(datum)
        if execution_id is None:
            return None
        return reverse(
            'horizon:powerops:compute_hosts:execution',
            args=(execution_id,),
        )


class ComputeHostsTable(tables.DataTable):
    region_name = tables.Column(
        'region_name', verbose_name=_('Region'))
    segment_uuid = tables.Column(
        'segment_uuid', verbose_name=_('Masakari segment'))
    host = tables.Column('host', verbose_name=_('Compute host'))
    ironic_node_uuid = tables.Column(
        'ironic_node_uuid', verbose_name=_('Ironic node'))
    power_state = tables.Column(
        'power_state',
        verbose_name=_('Power state'),
        status=True,
        status_choices=POWER_STATUS_CHOICES,
    )
    target_power_state = tables.Column(
        'target_power_state',
        verbose_name=_('Target power state'),
        status=True,
        status_choices=POWER_STATUS_CHOICES,
    )
    nova_status = tables.Column(
        'nova_status',
        verbose_name=_('Nova status'),
        status=True,
        status_choices=NOVA_STATUS_CHOICES,
    )
    nova_state = tables.Column(
        'nova_state',
        verbose_name=_('Nova state'),
        status=True,
        status_choices=NOVA_STATE_CHOICES,
    )
    masakari_maintenance = tables.Column(
        maintenance_status,
        verbose_name=_('Masakari maintenance'),
        status=True,
        status_choices=(
            ('normal', True),
            ('maintenance', False),
            ('unknown', None),
        ),
    )
    instance_count = tables.Column(
        'instance_count', verbose_name=_('VM count'))
    instances = tables.Column(
        instance_summary, verbose_name=_('Instances'))
    active_execution = ActiveExecutionColumn(
        'active_execution',
        verbose_name=_('Active execution'),
        link=True,
    )
    blocking_reason = tables.Column(
        blocking_reason, verbose_name=_('Availability'))

    def get_object_id(self, datum):
        return '{}-{}'.format(datum.segment_uuid, datum.host)

    class Meta(object):
        name = 'compute_hosts'
        verbose_name = _('Compute Hosts')
        table_actions = ()
        row_actions = ()
        multi_select = False
        status_columns = (
            'power_state',
            'target_power_state',
            'nova_status',
            'nova_state',
            'masakari_maintenance',
        )
