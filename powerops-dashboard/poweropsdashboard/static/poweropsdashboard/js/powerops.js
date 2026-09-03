(function(factory) {
  'use strict';

  if (typeof module === 'object' && module.exports) {
    module.exports = factory;
  } else {
    document.addEventListener('DOMContentLoaded', function() {
      factory(document);
    });
  }
}(function initializePowerOpsPolicy(document) {
  'use strict';

  var policies = {
    require_empty: true,
    live_migrate: true,
    stop: true
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

  if (!select || !submit || !current) {
    return;
  }
  if (select.powerOpsPolicyInitialized === true) {
    return;
  }
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
}));
