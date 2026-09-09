from django.core.exceptions import PermissionDenied


class RegionMismatch(Exception):
    pass


class InvalidBackendData(Exception):
    pass


class MockMutationDisabled(Exception):
    pass


__all__ = (
    'InvalidBackendData',
    'MockMutationDisabled',
    'PermissionDenied',
    'RegionMismatch',
)
