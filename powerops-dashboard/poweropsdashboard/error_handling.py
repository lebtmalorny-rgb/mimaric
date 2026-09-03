import logging

from django.core.exceptions import PermissionDenied

from poweropsdashboard import exceptions
from poweropsdashboard import submission


LOG = logging.getLogger(__name__)

_FORBIDDEN = (403, 'Недостаточно прав для операции PowerOps.', False)
_CONFLICT = (409, 'Хост занят или его состояние изменилось.', False)
_INVALID = (422, 'Параметры операции не прошли проверку.', False)
_UNAVAILABLE = (503, 'Обязательный сервис временно недоступен.', True)


def _http_status(exc):
    for name in ('http_status', 'status_code', 'error_code', 'code'):
        value = getattr(exc, name, None)
        if type(value) is int:
            return value
    return None


def classify_error(exc):
    if isinstance(exc, PermissionDenied):
        return _FORBIDDEN
    if isinstance(exc, (submission.SubmissionConflict,
                        exceptions.MockMutationDisabled)):
        return _CONFLICT
    if isinstance(exc, (submission.InvalidSubmission,
                        exceptions.InvalidBackendData)):
        return _INVALID
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return _UNAVAILABLE

    status = _http_status(exc)
    if status in (401, 403):
        return _FORBIDDEN
    if status == 409:
        return _CONFLICT
    if status in (400, 422):
        return _INVALID
    if status is not None and status >= 500:
        return _UNAVAILABLE

    LOG.error(
        'Unhandled PowerOps failure [exception_type=%s]',
        type(exc).__name__,
    )
    return _UNAVAILABLE
