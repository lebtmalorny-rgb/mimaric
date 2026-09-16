# Masakari PowerOps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fail-closed Ironic fencing and cluster-wide sequential VM evacuation to vanilla Masakari 19.1.0 from `stable/2025.1`.

**Architecture:** `TaskFlowDriver.execute_host_failure()` owns one etcd/tooz per-host lock for the complete recovery flow. A custom `IronicFenceTask` proves stable physical power-off before preparation, and the existing evacuation task uses the same coordinator to hold one global lock across each Nova evacuation and confirmation.

**Tech Stack:** Python 3.9+, Masakari TaskFlow, openstacksdk, tooz with etcd3gw, oslo.config, stestr.

**Spec:** `docs/superpowers/specs/2026-08-31-openstack-powerops-design.md`

## Global Constraints

- Baseline is vanilla Masakari commit `0fd34dd` (`19.1.0`, `stable/2025.1`).
- Ironic is power-only; no provisioning, cleaning, inspection or transition to `available` is permitted.
- Emergency order is Nova disable, physical fencing, stable-off proof, instance preparation, evacuation.
- A fencing or coordination failure must stop before evacuation.
- The per-host lock spans the complete host-failure workflow.
- The global lock spans one Nova evacuation, its confirmation and the pacing interval.
- The existing non-PowerOps flow remains unchanged when `[powerops] enabled=false`.
- No test may contact a real etcd endpoint, OpenStack API or BMC.

---

### Task 1: PowerOps configuration and tooz coordinator

**Files:**
- Create: `masakari/conf/powerops.py`
- Create: `masakari/powerops/__init__.py`
- Create: `masakari/powerops/coordination.py`
- Modify: `masakari/conf/__init__.py`
- Test: `masakari/tests/unit/powerops/__init__.py`
- Test: `masakari/tests/unit/powerops/test_coordination.py`

**Interfaces:**
- Produces: `host_lock_name(host: str) -> str`.
- Produces: `GLOBAL_EVACUATION_LOCK = "powerops/evacuation/global"`.
- Produces: `PowerOpsCoordinator(member_id: str, backend_url: str | None = None)` with `start()`, `stop()` and `lock(name: str, timeout: float)`.
- Consumes: existing `[coordination] backend_url` and new `[powerops]` options.

- [ ] **Step 1: Write failing coordinator tests**

```python
from unittest import mock

from tooz import coordination as tooz_coordination

from masakari.powerops import coordination
from masakari import test


class PowerOpsCoordinatorTest(test.TestCase):
    def test_host_lock_name_rejects_noncanonical_host(self):
        self.assertRaises(ValueError, coordination.host_lock_name, " host-1")

    @mock.patch.object(tooz_coordination, "get_coordinator")
    def test_lock_uses_exact_shared_namespace(self, get_coordinator):
        backend = mock.Mock()
        lock = mock.Mock()
        lock.acquire.return_value = True
        backend.get_lock.return_value = lock
        get_coordinator.return_value = backend

        coordinator = coordination.PowerOpsCoordinator(
            "notification-1", "etcd3+http://etcd:2379?api_version=v3"
        )
        with coordinator:
            with coordinator.lock(
                coordination.host_lock_name("compute-01"), 30
            ):
                pass

        backend.get_lock.assert_called_once_with(
            b"powerops/host/compute-01"
        )
        lock.acquire.assert_called_once_with(blocking=30)
        lock.release.assert_called_once_with()
        backend.start.assert_called_once_with(start_heart=True)
        backend.stop.assert_called_once_with()

    def test_enabled_powerops_requires_backend_url(self):
        self.override_config("enabled", True, "powerops")
        self.override_config("backend_url", None, "coordination")
        coordinator = coordination.PowerOpsCoordinator("notification-1")
        self.assertRaises(RuntimeError, coordinator.start)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python -m stestr run masakari.tests.unit.powerops.test_coordination
```

Expected: import failure for `masakari.powerops.coordination`.

- [ ] **Step 3: Register exact PowerOps options**

Implement `masakari/conf/powerops.py` with these defaults:

```python
powerops_opts = [
    cfg.BoolOpt("enabled", default=False),
    cfg.FloatOpt("host_lock_timeout", default=30.0, min=0.1),
    cfg.FloatOpt("evacuation_lock_timeout", default=3600.0, min=1.0),
    cfg.IntOpt("evacuation_interval", default=5, min=0),
    cfg.IntOpt("power_timeout", default=180, min=1),
    cfg.IntOpt("poll_interval", default=5, min=1),
    cfg.IntOpt("stable_off_observations", default=3, min=2),
    cfg.StrOpt("region_name", default="RegionOne"),
    cfg.StrOpt("interface", default="internal"),
]
```

Expose `register_opts(conf)` and `list_opts()`, then import and register the
module from `masakari/conf/__init__.py` in the same pattern as
`masakari.conf.coordination`.

- [ ] **Step 4: Implement the coordinator context manager**

Use the exact acquisition contract below:

```python
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
GLOBAL_EVACUATION_LOCK = "powerops/evacuation/global"


def host_lock_name(host):
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        raise ValueError("host must be a canonical Nova hostname")
    return "powerops/host/{}".format(host)


@contextlib.contextmanager
def lock(self, name, timeout):
    if not self.started:
        raise RuntimeError("PowerOps coordinator is not started")
    backend_lock = self.coordinator.get_lock(name.encode("utf-8"))
    acquired = backend_lock.acquire(blocking=timeout)
    if not acquired:
        raise RuntimeError("timed out acquiring lock {}".format(name))
    try:
        yield
    finally:
        backend_lock.release()
```

`start()` must call `tooz.coordination.get_coordinator()` and
`start(start_heart=True)`. `stop()` must be idempotent. `__enter__` and
`__exit__` delegate to those methods.

- [ ] **Step 5: Run focused and configuration tests**

```bash
python -m stestr run \
  masakari.tests.unit.powerops.test_coordination \
  masakari.tests.unit.test_config
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add masakari/conf masakari/powerops masakari/tests/unit/powerops
git commit -m "feat: add PowerOps coordination primitives"
```

---

### Task 2: Ironic power client and fencing TaskFlow task

**Files:**
- Create: `masakari/powerops/ironic.py`
- Create: `masakari/engine/drivers/taskflow/powerops.py`
- Modify: `requirements.txt`
- Modify: `setup.cfg`
- Create: `masakari/tests/unit/powerops/fakes.py`
- Test: `masakari/tests/unit/powerops/test_ironic.py`
- Test: `masakari/tests/unit/engine/drivers/taskflow/test_powerops.py`

**Interfaces:**
- Consumes: `openstack.connection.Connection` authenticated with Masakari's service credentials.
- Produces: `IronicPowerClient(connection, sleep=eventlet.sleep, monotonic=time.monotonic)`.
- Produces: `IronicPowerClient.fence(host, timeout, interval, stable_observations) -> dict`.
- Produces: entry point `masakari.task_flow.tasks/ironic_fence`.
- Consumes: `powerops_coordinator` injected by TaskFlowDriver; the fencing task does not acquire or release the enclosing host lock.

- [ ] **Step 1: Add failing exact-node and power-state tests**

Create the shared test factories first:

```python
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock


def node(node_id, name, power_state, target_power_state=None,
         last_error=None, provision_state="manageable",
         network_interface="noop"):
    return SimpleNamespace(
        id=node_id,
        name=name,
        power_state=power_state,
        target_power_state=target_power_state,
        last_error=last_error,
        provision_state=provision_state,
        network_interface=network_interface,
    )


def connection(nodes):
    result = mock.Mock()
    result.baremetal.nodes.return_value = nodes
    result.baremetal.get_node.side_effect = lambda node_id: next(
        item for item in nodes if item.id == node_id
    )
    return result


def connection_with_node_states(states):
    result = connection([states[0]])
    result.baremetal.get_node.side_effect = iter(states[1:])
    return result


def monotonic(values):
    iterator = iter(values)
    return lambda: next(iterator)


class _RecordingCoordinator:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("coordinator-start")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("coordinator-stop")

    @contextmanager
    def lock(self, name, timeout):
        event = (
            "host-lock" if name.startswith("powerops/host/")
            else "evacuation-lock"
        )
        self.events.append(event + "-enter")
        try:
            yield
        finally:
            self.events.append(event + "-exit")

    def lock_count(self, name):
        prefix = (
            "host-lock" if name.startswith("powerops/host/")
            else "evacuation-lock"
        )
        return self.events.count(prefix + "-enter")


def recording_coordinator(events):
    return _RecordingCoordinator(events)
```

Import this module as `fakes` from each new PowerOps test module; keep the
existing Masakari unit fakes under a different import alias when both are
needed.

```python
def test_fence_rejects_duplicate_node_names(self):
    connection = fakes.connection(nodes=[
        fakes.node("node-1", "compute-01", "power on"),
        fakes.node("node-2", "compute-01", "power on"),
    ])
    client = ironic.IronicPowerClient(connection)
    self.assertRaises(
        ironic.FencingError, client.fence, "compute-01", 30, 1, 3
    )


def test_fence_rejects_off_with_pending_power_on(self):
    node = fakes.node(
        "node-1", "compute-01", "power off",
        target_power_state="power on",
    )
    client = ironic.IronicPowerClient(fakes.connection(nodes=[node]))
    self.assertRaises(
        ironic.FencingError, client.fence, "compute-01", 30, 1, 3
    )


def test_fence_requires_three_stable_off_observations(self):
    states = [
        fakes.node("node-1", "compute-01", "power on"),
        fakes.node("node-1", "compute-01", "power off"),
        fakes.node("node-1", "compute-01", "power off"),
        fakes.node("node-1", "compute-01", "power off"),
    ]
    connection = fakes.connection_with_node_states(states)
    result = ironic.IronicPowerClient(connection, sleep=lambda _n: None).fence(
        "compute-01", 30, 1, 3
    )
    self.assertEqual("power off", result["power_state"])
    connection.baremetal.set_node_power_state.assert_called_once_with(
        states[0], "power off", wait=False
    )
```

Cover non-empty `last_error`, `manageable`/`noop` validation, unknown power
state timeout and the already-stably-off idempotent path with these tests:

```python
@ddt.data(
    ("provision_state", "available"),
    ("network_interface", "flat"),
    ("last_error", "BMC communication failed"),
)
@ddt.unpack
def test_fence_rejects_unsafe_node_fields(self, field, value):
    node = fakes.node("node-1", "compute-01", "power on")
    setattr(node, field, value)
    client = ironic.IronicPowerClient(fakes.connection(nodes=[node]))
    self.assertRaises(
        ironic.FencingError, client.fence, "compute-01", 30, 1, 3
    )


def test_fence_times_out_on_unknown_power_state(self):
    clock = fakes.monotonic([0, 0, 2])
    node = fakes.node("node-1", "compute-01", None)
    client = ironic.IronicPowerClient(
        fakes.connection(nodes=[node]),
        sleep=lambda _n: None,
        monotonic=clock,
    )
    self.assertRaises(
        ironic.FencingError, client.fence, "compute-01", 1, 1, 3
    )


def test_fence_already_off_is_idempotent(self):
    states = [
        fakes.node("node-1", "compute-01", "power off"),
        fakes.node("node-1", "compute-01", "power off"),
        fakes.node("node-1", "compute-01", "power off"),
    ]
    connection = fakes.connection_with_node_states(states)
    ironic.IronicPowerClient(
        connection, sleep=lambda _n: None
    ).fence("compute-01", 30, 1, 3)
    connection.baremetal.set_node_power_state.assert_not_called()
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m stestr run \
  masakari.tests.unit.powerops.test_ironic \
  masakari.tests.unit.engine.drivers.taskflow.test_powerops
```

Expected: import failure for `masakari.powerops.ironic`.

- [ ] **Step 3: Add constrained dependencies and the entry point**

Append these OpenStack-global-requirements-compatible lines:

```text
etcd3gw!=0.2.2,!=0.2.3,!=0.2.6 # Apache-2.0
openstacksdk # Apache-2.0
```

Add to `[entry_points] masakari.task_flow.tasks`:

```ini
ironic_fence = masakari.engine.drivers.taskflow.powerops:IronicFenceTask
```

- [ ] **Step 4: Implement the fail-closed Ironic client**

`connection_from_conf()` must build a Keystone session from
`[keystone_authtoken]` and return an `openstack.connection.Connection` using
the configured region and interface. Never log the auth configuration.

Implement the acceptance predicate exactly:

```python
def _is_compatible_off(node):
    return (
        node.power_state == "power off"
        and node.target_power_state in (None, "power off")
        and not node.last_error
    )
```

`fence()` must list detailed nodes, require one exact name, require
`provision_state == "manageable"` and `network_interface == "noop"`, reject
any conflicting pending target even when current state is already off, send
hard `power off` only when necessary, and count consecutive compatible
observations until the configured threshold.

- [ ] **Step 5: Implement `IronicFenceTask`**

```python
class IronicFenceTask(base.MasakariTask):
    def __init__(self, context, novaclient, **kwargs):
        kwargs["requires"] = ["host_name"]
        self.powerops_coordinator = kwargs.pop("powerops_coordinator", None)
        super().__init__(context, novaclient, **kwargs)

    def execute(self, host_name):
        if not CONF.powerops.enabled or self.powerops_coordinator is None:
            raise exception.HostRecoveryFailureException(
                message="PowerOps coordinator is required for fencing"
            )
        return ironic.IronicPowerClient(
            ironic.connection_from_conf()
        ).fence(
            host_name,
            CONF.powerops.power_timeout,
            CONF.powerops.poll_interval,
            CONF.powerops.stable_off_observations,
        )

    def revert(self, host_name, result, flow_failures):
        LOG.critical(
            "Fenced host %s remains powered off after flow failure", host_name
        )
```

The revert method contains no connection creation and no power-on call.

- [ ] **Step 6: Run focused tests and inspect the installed entry point**

```bash
python -m stestr run \
  masakari.tests.unit.powerops.test_ironic \
  masakari.tests.unit.engine.drivers.taskflow.test_powerops
python -c "import importlib.metadata as m; assert any(e.name == 'ironic_fence' for e in m.entry_points(group='masakari.task_flow.tasks'))"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt setup.cfg masakari/powerops/ironic.py \
  masakari/engine/drivers/taskflow/powerops.py \
  masakari/tests/unit/powerops/fakes.py \
  masakari/tests/unit/powerops/test_ironic.py \
  masakari/tests/unit/engine/drivers/taskflow/test_powerops.py
git commit -m "feat: fence failed hosts through Ironic"
```

---

### Task 3: Hold the host lock across the complete failure flow

**Files:**
- Modify: `masakari/engine/drivers/taskflow/driver.py`
- Modify: `masakari/engine/drivers/taskflow/host_failure.py`
- Modify: `masakari/tests/unit/engine/drivers/taskflow/test_taskflow_driver.py`

**Interfaces:**
- Consumes: `PowerOpsCoordinator` and `host_lock_name()` from Task 1.
- Produces: `powerops_coordinator` constructor keyword for every configured host-failure task.
- Preserves: all four recovery methods and reserved-host retry semantics.

- [ ] **Step 1: Add a failing whole-flow lock-order test**

```python
@mock.patch.object(powerops_coordination, "PowerOpsCoordinator")
def test_powerops_host_lock_wraps_complete_auto_flow(self, coordinator_cls):
    events = []
    coordinator = fakes.recording_coordinator(events)
    coordinator_cls.return_value = coordinator
    self.override_config("enabled", True, "powerops")
    self._patch_auto_flow(events)

    self.taskflow_driver.execute_host_failure(
        self.ctxt,
        "compute-01",
        fields.FailoverSegmentRecoveryMethod.AUTO,
        uuidsentinel.fake_notification,
    )

    self.assertEqual(
        ["coordinator-start", "host-lock-enter", "flow-run",
         "host-lock-exit", "coordinator-stop"],
        events,
    )
```

Use this second test to prove AUTO_PRIORITY keeps one host lock while falling
back from auto to reserved-host recovery:

```python
@mock.patch.object(powerops_coordination, "PowerOpsCoordinator")
def test_auto_priority_fallback_keeps_same_host_lock(self, coordinator_cls):
    events = []
    coordinator_cls.return_value = fakes.recording_coordinator(events)
    self.override_config("enabled", True, "powerops")
    with mock.patch.object(
            self.taskflow_driver, "_execute_auto_workflow",
            side_effect=lambda *args, **kwargs: (
                events.append("auto-flow"),
                (_ for _ in ()).throw(RuntimeError("auto failed")),
            )[1]), \
            mock.patch.object(
                self.taskflow_driver, "_execute_rh_workflow",
                side_effect=lambda *args, **kwargs: events.append("rh-flow")):
        self.taskflow_driver.execute_host_failure(
            self.ctxt,
            "compute-01",
            fields.FailoverSegmentRecoveryMethod.AUTO_PRIORITY,
            uuidsentinel.fake_notification,
            reserved_host_list=["compute-02"],
        )
    self.assertEqual(
        ["coordinator-start", "host-lock-enter", "auto-flow", "rh-flow",
         "host-lock-exit", "coordinator-stop"],
        events,
    )
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m stestr run \
  masakari.tests.unit.engine.drivers.taskflow.test_taskflow_driver
```

Expected: no PowerOps coordinator calls are observed.

- [ ] **Step 3: Refactor host-failure dispatch under one context**

Move the current recovery-method branch into this exact private method:

```python
def _dispatch_host_failure(self, context, host_name, recovery_method,
                           notification_uuid, powerops_coordinator=None,
                           **kwargs):
    novaclient = nova.API()
    process_what = {
        "host_name": host_name,
        "notification_uuid": notification_uuid,
    }
    if recovery_method == fields.FailoverSegmentRecoveryMethod.AUTO:
        return self._execute_auto_workflow(
            context, novaclient, process_what,
            powerops_coordinator=powerops_coordinator,
        )
    if recovery_method == fields.FailoverSegmentRecoveryMethod.RESERVED_HOST:
        return self._execute_rh_workflow(
            context, novaclient, process_what,
            powerops_coordinator=powerops_coordinator,
            **kwargs
        )
    if recovery_method == fields.FailoverSegmentRecoveryMethod.AUTO_PRIORITY:
        return self._execute_auto_priority_workflow(
            context, novaclient, process_what,
            powerops_coordinator=powerops_coordinator,
            **kwargs
        )
    return self._execute_rh_priority_workflow(
        context, novaclient, process_what,
        powerops_coordinator=powerops_coordinator,
        **kwargs
    )
```

Implement the public method's PowerOps branch as:

```python
if not CONF.powerops.enabled:
    return self._dispatch_host_failure(
        context, host_name, recovery_method, notification_uuid, None, **kwargs
    )

with powerops_coordination.PowerOpsCoordinator(notification_uuid) as coord:
    with coord.lock(
        powerops_coordination.host_lock_name(host_name),
        CONF.powerops.host_lock_timeout,
    ):
        return self._dispatch_host_failure(
            context, host_name, recovery_method, notification_uuid,
            coord, **kwargs
        )
```

Translate coordinator errors to `HostRecoveryFailureException` without
running a TaskFlow.

- [ ] **Step 4: Thread the coordinator through all host-flow builders**

Add `powerops_coordinator=None` to `_execute_auto_workflow`,
`_execute_rh_workflow`, both priority helpers, `get_auto_flow()` and
`get_rh_flow()`. Pass it to every `base.get_recovery_flow()` call as the
keyword `powerops_coordinator=powerops_coordinator`.

- [ ] **Step 5: Run focused and existing driver tests**

```bash
python -m stestr run \
  masakari.tests.unit.engine.drivers.taskflow.test_taskflow_driver \
  masakari.tests.unit.engine.drivers.taskflow.test_host_failure_flow
```

Expected: PASS for PowerOps-enabled and legacy paths.

- [ ] **Step 6: Commit**

```bash
git add masakari/engine/drivers/taskflow/driver.py \
  masakari/engine/drivers/taskflow/host_failure.py \
  masakari/tests/unit/engine/drivers/taskflow/test_taskflow_driver.py
git commit -m "feat: lock complete Masakari host recovery"
```

---

### Task 4: Serialize complete VM evacuation across the cluster

**Files:**
- Modify: `masakari/engine/drivers/taskflow/host_failure.py`
- Modify: `masakari/tests/unit/engine/drivers/taskflow/test_host_failure_flow.py`

**Interfaces:**
- Consumes: injected `powerops_coordinator` and `GLOBAL_EVACUATION_LOCK`.
- Produces: deterministic ascending `instance_uuid` order per notification.
- Preserves: upstream parallel GreenPool behavior when PowerOps is disabled.

- [ ] **Step 1: Add failing serialization tests**

```python
def test_powerops_evacuation_is_sorted_and_globally_serial(self):
    events = []
    coordinator = fakes.recording_coordinator(events)
    task = host_failure.EvacuateInstancesTask(
        self.ctxt,
        self.novaclient,
        update_host_method=manager.update_host_method,
        powerops_coordinator=coordinator,
    )
    self.override_config("enabled", True, "powerops")
    self.override_config("evacuation_interval", 7, "powerops")
    self._create_pending_vmoves(["vm-b", "vm-a"])

    with mock.patch.object(task, "_evacuate_and_confirm") as evacuate, \
            mock.patch.object(eventlet, "sleep") as sleep:
        evacuate.side_effect = self._mark_succeeded
        task.execute("compute-01", self.notification_uuid)

    self.assertEqual(["vm-a", "vm-b"], [
        call.args[1].instance_uuid for call in evacuate.call_args_list
    ])
    self.assertEqual(2, coordinator.lock_count(
        powerops_coordination.GLOBAL_EVACUATION_LOCK
    ))
    self.assertEqual([mock.call(7), mock.call(7)], sleep.call_args_list)


def test_powerops_stops_after_first_failed_vmove(self):
    coordinator = fakes.recording_coordinator([])
    task = host_failure.EvacuateInstancesTask(
        self.ctxt,
        self.novaclient,
        update_host_method=manager.update_host_method,
        powerops_coordinator=coordinator,
    )
    self.override_config("enabled", True, "powerops")
    vm_a = mock.Mock(
        instance_uuid="vm-a", status=fields.VMoveStatus.PENDING
    )
    vm_b = mock.Mock(
        instance_uuid="vm-b", status=fields.VMoveStatus.PENDING
    )

    def mark_failed(_context, vmove, _reserved_host=None):
        vmove.status = fields.VMoveStatus.FAILED

    with mock.patch.object(
            objects.VMoveList, "get_all_vmoves",
            return_value=[vm_b, vm_a]), \
            mock.patch.object(
                task, "_evacuate_and_confirm",
                side_effect=mark_failed) as evacuate, \
            mock.patch.object(eventlet, "sleep") as sleep:
        self.assertRaises(
            exception.HostRecoveryFailureException,
            task.execute,
            "compute-01",
            self.notification_uuid,
        )

    self.assertEqual("vm-a", evacuate.call_args.args[1].instance_uuid)
    self.assertEqual(1, evacuate.call_count)
    sleep.assert_not_called()
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m stestr run \
  masakari.tests.unit.engine.drivers.taskflow.test_host_failure_flow
```

Expected: current GreenPool schedules the unsorted list without a global lock.

- [ ] **Step 3: Implement the PowerOps serial branch**

Store `powerops_coordinator` in `EvacuateInstancesTask.__init__`. Sort pending
VMoves before logging or execution. When PowerOps is enabled, replace the
GreenPool branch with:

```python
for vmove in sorted(all_vmoves, key=lambda item: item.instance_uuid):
    with self.powerops_coordinator.lock(
        powerops_coordination.GLOBAL_EVACUATION_LOCK,
        CONF.powerops.evacuation_lock_timeout,
    ):
        self._evacuate_and_confirm(self.context, vmove, reserved_host)
        if vmove.status == fields.VMoveStatus.FAILED:
            break
        eventlet.sleep(CONF.powerops.evacuation_interval)
```

Raise `HostRecoveryFailureException` after the first failed VMove. The lock
must remain held while `_evacuate_and_confirm()` performs Nova evacuation and
its existing confirmation polling.

- [ ] **Step 4: Prove the legacy branch still uses GreenPool**

Use this test with `[powerops] enabled=false` to prove the legacy branch still
constructs `greenpool.GreenPool(CONF.host_failure_recovery_threads)`:

```python
@mock.patch.object(greenpool, "GreenPool")
@mock.patch.object(objects.VMoveList, "get_all_vmoves", return_value=[])
def test_legacy_evacuation_uses_configured_greenpool(
        self, get_vmoves, greenpool_cls):
    self.override_config("enabled", False, "powerops")
    task = host_failure.EvacuateInstancesTask(
        self.ctxt,
        self.novaclient,
        update_host_method=manager.update_host_method,
    )
    task.execute("compute-01", self.notification_uuid)
    greenpool_cls.assert_called_once_with(
        CONF.host_failure_recovery_threads
    )
```

- [ ] **Step 5: Run all host-failure tests**

```bash
python -m stestr run \
  masakari.tests.unit.engine.drivers.taskflow.test_host_failure_flow \
  masakari.tests.unit.engine.drivers.taskflow.test_taskflow_driver
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add masakari/engine/drivers/taskflow/host_failure.py \
  masakari/tests/unit/engine/drivers/taskflow/test_host_failure_flow.py
git commit -m "feat: serialize Masakari evacuations through etcd"
```

---

### Task 5: Release note and Masakari patch verification

**Files:**
- Create: `releasenotes/notes/powerops-ironic-fencing.yaml`
- Test: existing Masakari test and lint suites.

**Interfaces:**
- Produces: four numbered Masakari commits suitable for `git format-patch`.

- [ ] **Step 1: Write the release note**

Document that the feature is disabled by default, requires an etcd-compatible
tooz URL and openstacksdk, inserts `ironic_fence` through the configured
TaskFlow list, and serializes evacuations only when enabled.

- [ ] **Step 2: Run the complete repository suite**

```bash
tox -e py3
tox -e pep8
```

Expected: PASS with no new warnings attributable to PowerOps.

- [ ] **Step 3: Verify safety strings and diff hygiene**

```bash
git diff --check stable/2025.1...HEAD
rg -n "power on" masakari/engine/drivers/taskflow/powerops.py
rg -n "powerops/host/|powerops/evacuation/global" masakari tests
```

Expected: the fencing task has no power-on call; both exact shared lock names
are present in production code and tests.

- [ ] **Step 4: Commit the release note**

```bash
git add releasenotes/notes/powerops-ironic-fencing.yaml
git commit -m "docs: describe Masakari PowerOps fencing"
```

- [ ] **Step 5: Export and dry-run the patch series**

```bash
POWEROPS_ARTIFACT_ROOT=/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches
git format-patch --output-directory \
  "$POWEROPS_ARTIFACT_ROOT/patches/masakari" stable/2025.1..HEAD
git worktree add /tmp/masakari-powerops-apply stable/2025.1
git -C /tmp/masakari-powerops-apply am \
  "$POWEROPS_ARTIFACT_ROOT"/patches/masakari/*.patch
git -C /tmp/masakari-powerops-apply diff --check stable/2025.1...HEAD
```

Expected: every patch applies in order without fuzz or rejects.
