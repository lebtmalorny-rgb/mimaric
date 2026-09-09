(function(factory) {
  'use strict';

  if (typeof module === 'object' && module.exports) {
    module.exports = factory;
  } else {
    document.addEventListener('DOMContentLoaded', function() {
      factory(document, window);
    });
  }
}(function initializePowerOps(document, runtime) {
  'use strict';

  var policies = {
    require_empty: true,
    live_migrate: true,
    stop: true
  };
  var states = {
    IDLE: true,
    RUNNING: true,
    SUCCESS: true,
    ERROR: true,
    PAUSED: true,
    CANCELLED: true,
    DELAYED: true,
    WAITING: true
  };
  var terminalStates = {
    SUCCESS: true,
    ERROR: true,
    CANCELLED: true
  };
  var select = document.querySelector('[data-powerops-policy-select]');
  var submit = document.querySelector('[data-powerops-submit]');
  var current = document.querySelector('[data-powerops-policy-result]');
  var selected = document.querySelectorAll(
    '[data-powerops-selected-policy]'
  );
  var definitions = document.querySelectorAll(
    '[data-powerops-policy-consequence]'
  );
  var consequences = {};
  var definitionsValid = true;

  if (select && submit && current &&
      select.powerOpsPolicyInitialized !== true) {
    select.powerOpsPolicyInitialized = true;

    Array.prototype.forEach.call(definitions, function(definition) {
      var policy = definition.getAttribute(
        'data-powerops-policy-consequence'
      );
      if (!Object.prototype.hasOwnProperty.call(policies, policy) ||
          Object.prototype.hasOwnProperty.call(consequences, policy)) {
        definitionsValid = false;
        return;
      }
      consequences[policy] = definition.textContent.trim();
    });
    if (Object.keys(consequences).length !== 3) {
      definitionsValid = false;
    }

    function updatePolicyConfirmation() {
      var policy = select.value;
      submit.disabled = true;
      current.textContent = '';
      Array.prototype.forEach.call(selected, function(output) {
        output.textContent = '';
      });

      if (!definitionsValid ||
          !Object.prototype.hasOwnProperty.call(policies, policy) ||
          !Object.prototype.hasOwnProperty.call(consequences, policy)) {
        return;
      }

      Array.prototype.forEach.call(selected, function(output) {
        output.textContent = policy;
      });
      current.textContent = consequences[policy];
      submit.disabled = false;
    }

    select.addEventListener('change', updatePolicyConfirmation);
    updatePolicyConfirmation();
  }

  var poll = document.querySelector('[data-powerops-execution-poll]');
  if (!poll || !runtime || poll.powerOpsPollingInitialized === true) {
    return;
  }

  var executionId = poll.getAttribute('data-powerops-execution-id');
  var rawUrl = poll.getAttribute('data-powerops-execution-url');
  var url;
  try {
    url = new URL(rawUrl, runtime.location.href);
  } catch (error) {
    return;
  }
  if (url.origin !== runtime.location.origin ||
      typeof runtime.fetch !== 'function' ||
      typeof runtime.setTimeout !== 'function') {
    return;
  }
  poll.powerOpsPollingInitialized = true;

  function validUuid(value) {
    return typeof value === 'string' &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
  }

  function validPayload(payload) {
    if (!payload || typeof payload !== 'object' ||
        Array.isArray(payload) ||
        Object.keys(payload).sort().join(',') !== 'id,state,tasks' ||
        payload.id !== executionId ||
        !Object.prototype.hasOwnProperty.call(states, payload.state) ||
        !Array.isArray(payload.tasks)) {
      return false;
    }
    return payload.tasks.every(function(task) {
      return task && typeof task === 'object' && !Array.isArray(task) &&
        Object.keys(task).sort().join(',') === 'id,state' &&
        validUuid(task.id) &&
        Object.prototype.hasOwnProperty.call(states, task.state);
    });
  }

  function updateStates(payload) {
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-powerops-execution-state]'),
      function(output) {
        output.textContent = payload.state;
      }
    );
    var taskStates = {};
    payload.tasks.forEach(function(task) {
      taskStates[task.id] = task.state;
    });
    Array.prototype.forEach.call(
      document.querySelectorAll('[data-powerops-task-state]'),
      function(output) {
        var taskId = output.getAttribute('data-powerops-task-id');
        if (Object.prototype.hasOwnProperty.call(taskStates, taskId)) {
          output.textContent = taskStates[taskId];
        }
      }
    );
  }

  function pollExecution() {
    runtime.fetch(url.href, {
      method: 'GET',
      credentials: 'same-origin',
      redirect: 'error',
      headers: {Accept: 'application/json'}
    }).then(function(response) {
      var responseUrl;
      var contentType = response.headers.get('content-type') || '';
      try {
        responseUrl = new URL(response.url, runtime.location.href);
      } catch (error) {
        throw new Error('invalid response URL');
      }
      if (!response.ok || responseUrl.origin !== runtime.location.origin ||
          contentType.split(';', 1)[0].trim() !== 'application/json') {
        throw new Error('invalid polling response');
      }
      return response.json();
    }).then(function(payload) {
      if (!validPayload(payload)) {
        throw new Error('invalid polling payload');
      }
      updateStates(payload);
      if (!Object.prototype.hasOwnProperty.call(
          terminalStates, payload.state)) {
        runtime.setTimeout(pollExecution, 2000);
      }
    }).catch(function() {
      return undefined;
    });
  }

  pollExecution();
}));
