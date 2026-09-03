from django import forms
from django.utils.translation import gettext_lazy as _

from poweropsdashboard import constants


_OPERATIONS = frozenset({'power_off', 'reboot'})
_COMMON_FIELDS = frozenset({
    'typed_host',
    'instance_policy',
    'submission_token',
})
_HARD_OFF_FIELDS = frozenset({'allow_hard_off', 'confirm_hard_off'})
_FRAMEWORK_FIELDS = frozenset({'csrfmiddlewaretoken'})


class PlannedOperationForm(forms.Form):
    typed_host = forms.CharField(
        label=_('Type the exact compute host name'),
        strip=False,
    )
    instance_policy = forms.ChoiceField(
        label=_('Instance policy'),
        choices=tuple(
            (policy, policy) for policy in constants.INSTANCE_POLICIES),
        initial='require_empty',
        widget=forms.Select(attrs={
            'data-powerops-policy-select': 'true',
        }),
    )
    submission_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, authorization, host_row, operation, *args, **kwargs):
        if operation not in _OPERATIONS:
            raise ValueError('Unsupported planned operation')
        self.authorization = authorization
        self.host_row = host_row
        self.operation = operation

        data = kwargs.get('data')
        if data is None and args:
            data = args[0]
        allowed = set(_COMMON_FIELDS | _FRAMEWORK_FIELDS)
        if operation == 'power_off' and authorization.is_admin:
            allowed.update(_HARD_OFF_FIELDS)
        self._ambiguous_browser_data = self._is_ambiguous(data, allowed)

        super().__init__(*args, **kwargs)
        if operation == 'power_off' and authorization.is_admin:
            self.fields['allow_hard_off'] = forms.BooleanField(
                label=_('Allow hard power-off if graceful shutdown fails'),
                required=False,
            )
            self.fields['confirm_hard_off'] = forms.BooleanField(
                label=_('I separately confirm hard power-off'),
                required=False,
            )

    @staticmethod
    def _is_ambiguous(data, allowed):
        if data is None:
            return False
        try:
            keys = set(data.keys())
        except (AttributeError, TypeError):
            return True
        if not keys.issubset(allowed):
            return True
        for key in keys:
            if hasattr(data, 'getlist'):
                values = data.getlist(key)
            else:
                value = data[key]
                values = value if isinstance(value, (list, tuple)) else [value]
            if len(values) != 1:
                return True
        return False

    def clean_typed_host(self):
        typed_host = self.cleaned_data['typed_host']
        if typed_host != self.host_row.host:
            raise forms.ValidationError(
                _('The compute host name does not match exactly.'))
        return typed_host

    def clean(self):
        cleaned_data = super().clean()
        if self._ambiguous_browser_data:
            raise forms.ValidationError(
                _('The submitted fields are not valid for this operation.'))

        if self.operation == 'power_off' and self.authorization.is_admin:
            allow_hard_off = cleaned_data.get('allow_hard_off') is True
            confirm_hard_off = cleaned_data.get('confirm_hard_off') is True
            if allow_hard_off != confirm_hard_off:
                self.add_error(
                    'confirm_hard_off',
                    _('Hard power-off requires a separate confirmation.'),
                )
        return cleaned_data

    def workflow_input(self):
        if not self.is_valid():
            raise ValueError('Cannot build input from an invalid form')
        return {
            'host': self.host_row.host,
            'segment_uuid': self.host_row.segment_uuid,
            'instance_policy': self.cleaned_data['instance_policy'],
            'allow_hard_off': (
                self.operation == 'power_off'
                and self.authorization.is_admin
                and self.cleaned_data.get('allow_hard_off') is True
            ),
        }
