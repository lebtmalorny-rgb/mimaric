import pathlib
import subprocess
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase

from poweropsdashboard import error_handling
from poweropsdashboard import exceptions
from poweropsdashboard import submission


EXPECTED = {
    'forbidden': (403, 'Недостаточно прав для операции PowerOps.', False),
    'conflict': (409, 'Хост занят или его состояние изменилось.', False),
    'invalid': (422, 'Параметры операции не прошли проверку.', False),
    'unavailable': (
        503,
        'Обязательный сервис временно недоступен.',
        True,
    ),
}


class ErrorClassificationTests(SimpleTestCase):

    def test_local_errors_map_to_fixed_public_classes(self):
        cases = (
            (PermissionDenied(), EXPECTED['forbidden']),
            (submission.SubmissionConflict('secret'), EXPECTED['conflict']),
            (exceptions.MockMutationDisabled('secret'), EXPECTED['conflict']),
            (submission.InvalidSubmission('secret'), EXPECTED['invalid']),
            (exceptions.InvalidBackendData('secret'), EXPECTED['invalid']),
            (TimeoutError('token=secret'), EXPECTED['unavailable']),
            (ConnectionError('password=secret'), EXPECTED['unavailable']),
        )

        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                self.assertEqual(
                    expected, error_handling.classify_error(error))

    def test_http_client_statuses_map_without_using_raw_message(self):
        for status, expected in (
                (403, EXPECTED['forbidden']),
                (409, EXPECTED['conflict']),
                (400, EXPECTED['invalid']),
                (422, EXPECTED['invalid']),
                (503, EXPECTED['unavailable'])):
            with self.subTest(status=status):
                error = RuntimeError('token=must-not-render')
                error.http_status = status
                self.assertEqual(
                    expected,
                    error_handling.classify_error(error),
                )

        mistral_error = RuntimeError('password=must-not-render')
        mistral_error.error_code = 409
        self.assertEqual(
            EXPECTED['conflict'],
            error_handling.classify_error(mistral_error),
        )

    @mock.patch.object(error_handling.LOG, 'error')
    def test_unknown_error_is_logged_by_type_but_secret_text_is_not_public(
            self, log_error):
        result = error_handling.classify_error(
            RuntimeError('Traceback token=password bmc_address driver_info'))

        self.assertEqual(EXPECTED['unavailable'], result)
        log_error.assert_called_once()
        self.assertNotIn('password', str(log_error.call_args))
        self.assertNotIn('bmc_address', str(log_error.call_args))
        self.assertNotIn('exc_info', str(log_error.call_args))


class PollingJavaScriptTests(SimpleTestCase):

    def test_polling_is_same_origin_get_only_and_stops_terminal(self):
        javascript = pathlib.Path(__file__).parents[1] / (
            'static/poweropsdashboard/js/powerops.js')
        probe = r"""
const assert = require('assert');
const initialize = require(process.argv[1]);
let calls = [];
let timers = [];
const executionState = {textContent: 'RUNNING'};
const taskState = {
  textContent: 'RUNNING',
  getAttribute: (name) => name === 'data-powerops-task-id'
    ? 'dddddddd-dddd-dddd-dddd-dddddddddddd' : null
};
const poll = {
  powerOpsPollingInitialized: false,
  getAttribute: (name) => ({
    'data-powerops-execution-url':
      '/powerops/executions/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/',
    'data-powerops-execution-id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
  })[name]
};
const document = {
  querySelector: (selector) => selector === '[data-powerops-execution-poll]'
    ? poll : null,
  querySelectorAll: (selector) => {
    if (selector === '[data-powerops-execution-state]') {
      return [executionState];
    }
    if (selector === '[data-powerops-task-state]') return [taskState];
    return [];
  }
};
const response = {
  ok: true,
  url: 'https://horizon.example/powerops/executions/' +
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/',
  headers: {get: () => 'application/json; charset=utf-8'},
  json: () => Promise.resolve({
    id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    state: 'SUCCESS',
    tasks: [{
      id: 'dddddddd-dddd-dddd-dddd-dddddddddddd',
      state: 'SUCCESS'
    }]
  })
};
const runtime = {
  location: {
    href: 'https://horizon.example/powerops/',
    origin: 'https://horizon.example'
  },
  fetch: (url, options) => {
    calls.push([url, options]);
    return Promise.resolve(response);
  },
  setTimeout: (fn, delay) => timers.push([fn, delay])
};
initialize(document, runtime);
setImmediate(() => {
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0][1].method, 'GET');
  assert.strictEqual(calls[0][1].headers.Accept, 'application/json');
  assert.strictEqual(executionState.textContent, 'SUCCESS');
  assert.strictEqual(taskState.textContent, 'SUCCESS');
  assert.strictEqual(timers.length, 0);
});
"""

        result = subprocess.run(
            ['node', '-e', probe, str(javascript)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)

    def test_polling_rejects_cross_origin_without_fetch(self):
        javascript = pathlib.Path(__file__).parents[1] / (
            'static/poweropsdashboard/js/powerops.js')
        probe = r"""
const assert = require('assert');
const initialize = require(process.argv[1]);
let calls = 0;
const poll = {
  getAttribute: (name) => ({
    'data-powerops-execution-url': 'https://evil.example/steal',
    'data-powerops-execution-id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
  })[name]
};
const document = {
  querySelector: (selector) => selector === '[data-powerops-execution-poll]'
    ? poll : null,
  querySelectorAll: () => []
};
initialize(document, {
  location: {
    href: 'https://horizon.example/',
    origin: 'https://horizon.example'
  },
  fetch: () => { calls += 1; },
  setTimeout: () => {}
});
assert.strictEqual(calls, 0);
"""

        result = subprocess.run(
            ['node', '-e', probe, str(javascript)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, result.returncode, result.stderr)
