# Mistral PowerOps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe composite planned host power actions and the stable `power_ops` workbook API to vanilla Mistral `stable/2025.1`.

**Architecture:** Every uninterrupted host transition runs inside one synchronous Python action that owns one etcd/tooz coordinator and per-host lock for its full state machine. The `power_on_and_return` workflow deliberately splits at a safe pause and receives the operator's `stale_domains_checked=true` assertion through the environment of the resume request.

**Tech Stack:** Python 3.9+, mistral-lib actions, openstacksdk, keystoneauth1, tooz with etcd3gw, oslo.config, YAML workbook DSL v2, stestr.

**Spec:** `docs/superpowers/specs/2026-08-31-openstack-powerops-design.md`

## Global Constraints

- Baseline is vanilla Mistral commit `3b2eab2` from `stable/2025.1`.
- Mistral handles planned operations only; it never calls Nova evacuation.
- Valid instance policies are exactly `require_empty`, `live_migrate` and `stop`.
- Every mutating composite action owns `powerops/host/<host>` from before the first state change through its final safe state.
- `power_on_for_inspection` and `return_to_service` use separate coordinator sessions because a tooz lock cannot be transferred between Executor processes.
- Planned failure after Nova disable leaves Nova disabled and Masakari maintenance enabled.
- Only UUIDs returned by the earlier `stop` policy may be restarted.
- Empty caller allowlists deny every action; project and user comparisons are exact.
- No test may contact a real etcd endpoint, OpenStack API or BMC.

---

### Task 1: PowerOps configuration and action-local coordination

**Files:**
- Modify: `mistral/config.py`
- Create: `mistral/actions/powerops/__init__.py`
- Create: `mistral/actions/powerops/coordination.py`
- Test: `mistral/tests/unit/actions/powerops/__init__.py`
- Test: `mistral/tests/unit/actions/powerops/test_coordination.py`

**Interfaces:**
- Produces: `[powerops]` configuration group.
- Produces: `host_lock_name(host: str) -> str`.
- Produces: `OperationCoordinator(member_id: str)` context manager.
- Produces: `OperationCoordinator.lock_host(host: str)` context manager.
- Consumes: `[powerops] coordination_url`; it does not reuse Mistral's deprecated service-membership `[coordination]` group.

- [ ] **Step 1: Write failing configuration and lock tests**

```python
from unittest import mock

from tooz import coordination as tooz_coordination

from mistral.actions.powerops import coordination
from mistral.tests.unit import base


class OperationCoordinatorTest(base.BaseTest):
    def test_host_lock_name_rejects_noncanonical_host(self):
        self.assertRaises(ValueError, coordination.host_lock_name, " host-1")

    @mock.patch.object(tooz_coordination, "get_coordinator")
    def test_action_owns_exact_host_lock(self, get_coordinator):
        backend = mock.Mock()
        lock = mock.Mock()
        lock.acquire.return_value = True
        backend.get_lock.return_value = lock
        get_coordinator.return_value = backend
        self.override_config(
            "coordination_url",
            "etcd3+http://etcd:2379?api_version=v3",
            "powerops",
        )

        with coordination.OperationCoordinator("action-1") as coordinator:
            with coordinator.lock_host("compute-01"):
                pass

        get_coordinator.assert_called_once_with(
            "etcd3+http://etcd:2379?api_version=v3", b"action-1"
        )
        backend.start.assert_called_once_with(start_heart=True)
        backend.get_lock.assert_called_once_with(
            b"powerops/host/compute-01"
        )
        lock.acquire.assert_called_once_with(blocking=30.0)
        lock.release.assert_called_once_with()
        backend.stop.assert_called_once_with()

    def test_enabled_powerops_requires_coordination_url(self):
        self.override_config("enabled", True, "powerops")
        self.override_config("coordination_url", None, "powerops")
        self.assertRaises(
            RuntimeError,
            coordination.OperationCoordinator("action-1").start,
        )
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m stestr run mistral.tests.unit.actions.powerops.test_coordination
```

Expected: import failure for `mistral.actions.powerops.coordination`.

- [ ] **Step 3: Register the exact PowerOps configuration contract**

Add this option list and register it as group `powerops` in `mistral/config.py`:

```python
powerops_opts = [
    cfg.BoolOpt("enabled", default=False),
    cfg.StrOpt("coordination_url", secret=True),
    cfg.FloatOpt("host_lock_timeout", default=30.0, min=0.1),
    cfg.IntOpt("power_timeout", default=180, min=1),
    cfg.IntOpt("poll_interval", default=5, min=1),
    cfg.IntOpt("stable_observations", default=3, min=2),
    cfg.IntOpt("graceful_shutdown_timeout", default=300, min=1),
    cfg.IntOpt("vm_action_timeout", default=600, min=1),
    cfg.IntOpt("service_timeout", default=300, min=1),
    cfg.IntOpt("instance_interval", default=5, min=0),
    cfg.StrOpt("region_name", default="RegionOne"),
    cfg.StrOpt("interface", default="internal"),
    cfg.StrOpt("nova_disable_reason", default="PowerOps planned operation"),
    cfg.ListOpt("allowed_project_names", default=[]),
    cfg.ListOpt("allowed_user_names", default=[]),
]

POWEROPS_GROUP = "powerops"
CONF.register_opts(powerops_opts, group=POWEROPS_GROUP)
```

Also return `(POWEROPS_GROUP, powerops_opts)` from `list_opts()`.

- [ ] **Step 4: Implement the action-local coordinator**

```python
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def host_lock_name(host):
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        raise ValueError("host must be a canonical Nova hostname")
    return "powerops/host/{}".format(host)


class OperationCoordinator:
    def __init__(self, member_id):
        self.member_id = member_id
        self.backend = None

    def start(self):
        url = CONF.powerops.coordination_url
        if not CONF.powerops.enabled or not url:
            raise RuntimeError("PowerOps etcd coordination is not configured")
        self.backend = tooz_coordination.get_coordinator(
            url, self.member_id.encode("utf-8")
        )
        self.backend.start(start_heart=True)

    @contextlib.contextmanager
    def lock_host(self, host):
        lock = self.backend.get_lock(host_lock_name(host).encode("utf-8"))
        if not lock.acquire(blocking=CONF.powerops.host_lock_timeout):
            raise RuntimeError("timed out acquiring host PowerOps lock")
        try:
            yield
        finally:
            lock.release()
```

Implement idempotent `stop()` plus `__enter__` and `__exit__`; `__exit__`
always stops the coordinator and never suppresses the protected exception.

- [ ] **Step 5: Run focused and configuration tests**

```bash
python -m stestr run \
  mistral.tests.unit.actions.powerops.test_coordination \
  mistral.tests.unit.test_config
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mistral/config.py mistral/actions/powerops \
  mistral/tests/unit/actions/powerops
git commit -m "feat: add PowerOps action coordination"
```

---

### Task 2: Exact OpenStack host, instance and power primitives

**Files:**
- Modify: `requirements.txt`
- Create: `mistral/actions/powerops/exceptions.py`
- Create: `mistral/actions/powerops/clients.py`
- Test: `mistral/tests/unit/actions/powerops/fakes.py`
- Test: `mistral/tests/unit/actions/powerops/test_clients.py`

**Interfaces:**
- Produces: `connection_from_conf() -> openstack.connection.Connection`.
- Produces: `CloudClients(connection, ha_adapter=None, sleep=time.sleep, monotonic=time.monotonic)`; a supplied adapter is used only for dependency injection, otherwise a Keystone HA adapter is constructed.
- Produces: exact resolution methods `ironic_node(host)`, `nova_service(host)`, `masakari_host(segment_uuid, host)`.
- Produces: `resolve_host_set(segment_uuid, host)`, `wait_nova_service(host, enabled, up)`, `require_stable_power_on(host)`, and `require_masakari_maintenance(segment_uuid, host, expected)`.
- Produces: deterministic VM methods `instances_on_host(host)`, `apply_instance_policy(host, policy) -> list[str]`, and `start_instances(instance_ids)`.
- Produces: stable power methods `power_off(host, allow_hard_off)`, `power_on(host)` and `power_status(host)`.

- [ ] **Step 1: Add failing exact-resolution and power tests**

Start `fakes.py` with these exact resource and context factories:

```python
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock


def node(node_id, name, power_state="power on",
         target_power_state=None, last_error=None,
         provision_state="manageable", network_interface="noop"):
    return SimpleNamespace(
        id=node_id, name=name, power_state=power_state,
        target_power_state=target_power_state, last_error=last_error,
        provision_state=provision_state,
        network_interface=network_interface,
    )


def server(server_id, host, status):
    return SimpleNamespace(
        id=server_id, hypervisor_hostname=host, status=status
    )


def service(service_id, host, state="up", is_disabled=False):
    return SimpleNamespace(
        id=service_id, host=host, binary="nova-compute",
        state=state, is_disabled=is_disabled,
    )


def masakari_host(host_id, name, on_maintenance=True):
    return SimpleNamespace(
        id=host_id, name=name, on_maintenance=on_maintenance
    )


def action_context(execution_id, project_name="operations",
                   user_name="powerops-operator"):
    return SimpleNamespace(
        security=SimpleNamespace(
            project_name=project_name, user_name=user_name
        ),
        execution=SimpleNamespace(
            action_execution_id=execution_id + "-action",
            workflow_execution_id=execution_id,
        ),
    )


def monotonic(values=None):
    values = iter(values or range(1000000))
    return lambda: next(values)


def cloud(ironic_nodes=None, instances=None, nova_services=None,
          masakari_hosts=None, events=None):
    events = events if events is not None else []
    connection = mock.Mock()
    nodes = list(ironic_nodes or [])
    servers = list(instances or [])
    services = list(nova_services or [])
    hosts = list(masakari_hosts or [])
    connection.baremetal.nodes.return_value = nodes
    connection.baremetal.get_node.side_effect = lambda node_id: next(
        item for item in nodes if item.id == node_id
    )
    connection.compute.services.return_value = services
    connection.compute.servers.return_value = servers

    def get_server(server_id):
        item = next(item for item in servers if item.id == server_id)
        events.append(("wait-active", server_id))
        return item

    def stop_server(item):
        events.append(("stop", item.id))
        item.status = "SHUTOFF"

    def start_server(item):
        events.append(("start", item.id))
        item.status = "ACTIVE"

    connection.compute.get_server.side_effect = get_server
    connection.compute.stop_server.side_effect = stop_server
    connection.compute.start_server.side_effect = start_server
    ha_adapter = mock.Mock()
    hosts_response = mock.Mock()
    hosts_response.json.return_value = {
        "hosts": [vars(item) for item in hosts]
    }
    ha_adapter.get.return_value = hosts_response
    return SimpleNamespace(
        connection=connection, ha_adapter=ha_adapter, events=events
    )


class _RecordingCoordinator:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("coordinator-start")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("coordinator-stop")

    @contextmanager
    def lock_host(self, host):
        self.events.append("host-lock-enter")
        try:
            yield
        finally:
            self.events.append("host-lock-exit")


def recording_coordinator(events):
    return _RecordingCoordinator(events)
```

```python
class CloudClientsTest(base.BaseTest):
    def test_ironic_node_requires_one_exact_name(self):
        cloud = fakes.cloud(ironic_nodes=[
            fakes.node("n1", "compute-01"),
            fakes.node("n2", "compute-01"),
        ])
        client = clients.CloudClients(
            cloud.connection, ha_adapter=cloud.ha_adapter,
            sleep=lambda _n: None,
        )
        self.assertRaises(
            exceptions.HostResolutionError,
            client.ironic_node,
            "compute-01",
        )

    def test_power_off_rejects_conflicting_target(self):
        cloud = fakes.cloud(ironic_nodes=[fakes.node(
            "n1", "compute-01", power_state="power off",
            target_power_state="power on",
        )])
        client = clients.CloudClients(
            cloud.connection, ha_adapter=cloud.ha_adapter,
            sleep=lambda _n: None,
        )
        self.assertRaises(
            exceptions.PowerStateError,
            client.power_off,
            "compute-01",
            False,
        )

    def test_stop_policy_returns_only_instances_stopped_by_workflow(self):
        cloud = fakes.cloud(instances=[
            fakes.server("vm-b", "compute-01", "ACTIVE"),
            fakes.server("vm-a", "compute-01", "SHUTOFF"),
        ])
        client = clients.CloudClients(
            cloud.connection, ha_adapter=cloud.ha_adapter,
            sleep=lambda _n: None, monotonic=fakes.monotonic()
        )
        self.assertEqual(
            ["vm-b"],
            client.apply_instance_policy("compute-01", "stop"),
        )

    def test_start_instances_is_sorted_sequential_and_paced(self):
        events = []
        cloud = fakes.cloud(
            instances=[
                fakes.server("vm-b", "compute-01", "SHUTOFF"),
                fakes.server("vm-a", "compute-01", "SHUTOFF"),
            ],
            events=events,
        )
        client = clients.CloudClients(
            cloud.connection,
            ha_adapter=cloud.ha_adapter,
            sleep=lambda seconds: events.append(("sleep", seconds)),
            monotonic=fakes.monotonic(),
        )
        client.start_instances(["vm-b", "vm-a"])
        self.assertEqual(
            [("start", "vm-a"), ("wait-active", "vm-a"), ("sleep", 5),
             ("start", "vm-b"), ("wait-active", "vm-b"), ("sleep", 5)],
            events,
        )
```

Cover a non-`manageable` Node, non-`noop` network interface, non-empty
`last_error`, duplicate Nova services, duplicate Masakari hosts, unsupported
VM states, and any policy outside the three allowed values with these tests.

Use this table-driven test so each rejection has a concrete assertion:

```python
@ddt.data(
    ("provision_state", "available"),
    ("network_interface", "flat"),
    ("last_error", "BMC communication failed"),
)
@ddt.unpack
def test_ironic_node_rejects_unsafe_node_fields(self, field, value):
    node = fakes.node("n1", "compute-01")
    setattr(node, field, value)
    cloud = fakes.cloud(ironic_nodes=[node])
    client = clients.CloudClients(
        cloud.connection, ha_adapter=cloud.ha_adapter
    )
    self.assertRaises(
        exceptions.HostResolutionError,
        client.ironic_node,
        "compute-01",
    )


@ddt.data("evacuate", "", None)
def test_instance_policy_allowlist(self, policy):
    cloud = fakes.cloud()
    client = clients.CloudClients(
        cloud.connection, ha_adapter=cloud.ha_adapter
    )
    self.assertRaises(
        exceptions.InstancePolicyError,
        client.apply_instance_policy,
        "compute-01",
        policy,
    )
```

```python
def test_nova_service_rejects_duplicate_exact_hosts(self):
    cloud = fakes.cloud(nova_services=[
        fakes.service("s1", "compute-01"),
        fakes.service("s2", "compute-01"),
    ])
    client = clients.CloudClients(
        cloud.connection, ha_adapter=cloud.ha_adapter
    )
    self.assertRaises(
        exceptions.HostResolutionError,
        client.nova_service,
        "compute-01",
    )


def test_masakari_host_rejects_duplicate_exact_names(self):
    cloud = fakes.cloud(masakari_hosts=[
        fakes.masakari_host("h1", "compute-01"),
        fakes.masakari_host("h2", "compute-01"),
    ])
    client = clients.CloudClients(
        cloud.connection, ha_adapter=cloud.ha_adapter
    )
    self.assertRaises(
        exceptions.HostResolutionError,
        client.masakari_host,
        "segment-1",
        "compute-01",
    )


def test_stop_policy_rejects_intermediate_vm_state(self):
    cloud = fakes.cloud(instances=[
        fakes.server("vm-a", "compute-01", "MIGRATING"),
    ])
    client = clients.CloudClients(
        cloud.connection, ha_adapter=cloud.ha_adapter
    )
    self.assertRaises(
        exceptions.InstancePolicyError,
        client.apply_instance_policy,
        "compute-01",
        "stop",
    )
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m stestr run mistral.tests.unit.actions.powerops.test_clients
```

Expected: import failure for `mistral.actions.powerops.clients`.

- [ ] **Step 3: Add constrained runtime dependencies**

Append the release-compatible requirements:

```text
etcd3gw!=0.2.2,!=0.2.3,!=0.2.6 # Apache-2.0
keystoneauth1>=3.4.0 # Apache-2.0
openstacksdk # Apache-2.0
```

- [ ] **Step 4: Implement authenticated connection creation**

Create a Keystone v3 password auth plugin from `[keystone_authtoken]`
`auth_url`, `username`, `password`, `project_name`, `user_domain_name` and
`project_domain_name`. Accept either the domain-name pair or the
`user_domain_id`/`project_domain_id` pair rendered by Kolla, preferring IDs
when present. Create a `keystoneauth1.session.Session`, passing
`cafile` as `verify` when configured, and return:

```python
return openstack.connection.Connection(
    session=ks_session,
    region_name=CONF.powerops.region_name,
    interface=CONF.powerops.interface,
)
```

Never log the auth object, password, token or complete coordination URL.

- [ ] **Step 5: Implement exact host and Masakari resolution**

Use these acceptance predicates:

```python
def _compatible_node(node):
    return (
        node.provision_state == "manageable"
        and node.network_interface == "noop"
        and not node.last_error
    )


def _compatible_power(node, expected):
    return (
        node.power_state == expected
        and node.target_power_state in (None, expected)
        and not node.last_error
    )
```

`ironic_node()` lists detailed nodes and filters `node.name == host` in Python.
`nova_service()` filters `binary == "nova-compute"` and `host == host`.
`masakari_host()` gets the named segment from the HA endpoint, lists its hosts,
and requires one object whose `name == host`. The Masakari request paths are:

```python
segments_url = "/segments/{}".format(segment_uuid)
hosts_url = "/segments/{}/hosts".format(segment_uuid)
host_url = "/segments/{}/hosts/{}".format(segment_uuid, host_uuid)
maintenance_body = {"host": {"on_maintenance": True}}
```

Create the authenticated adapter without constructing a deployment-specific
endpoint:

```python
ha_adapter = ks_adapter.Adapter(
    session=connection.session,
    service_type="ha",
    interface=CONF.powerops.interface,
    region_name=CONF.powerops.region_name,
)
```

Use `ha_adapter.get()` and `ha_adapter.put()` with the relative paths above.

- [ ] **Step 6: Implement deterministic instance and power transitions**

Implement one bounded polling helper:

```python
def _wait_until(self, probe, accept, timeout, description):
    deadline = self.monotonic() + timeout
    consecutive = 0
    while self.monotonic() < deadline:
        value = probe()
        consecutive = consecutive + 1 if accept(value) else 0
        if consecutive >= CONF.powerops.stable_observations:
            return value
        self.sleep(CONF.powerops.poll_interval)
    raise exceptions.PowerOpsTimeout(description)
```

For `require_empty`, fail if the sorted host instance list is non-empty. For
`stop`, accept only `ACTIVE` and `SHUTOFF`, stop each `ACTIVE` UUID in ascending
order, wait for `SHUTOFF`, append only that UUID to the manifest, then sleep
`instance_interval`. For `live_migrate`, migrate each UUID in ascending order,
wait until its hypervisor differs from the source and its status is stable,
then sleep `instance_interval`. Never call Nova evacuation.

For graceful off call Ironic with `soft=True`; if its timeout expires, call
hard off only when `allow_hard_off is True`. For hard off use `soft=False`.
For power on use `"power on"`. All successful transitions require consecutive
compatible observations and reject conflicting target state or `last_error`.
`resolve_host_set()` invokes all three exact resolvers before any mutation.
The three `wait_`/`require_` methods use the same bounded polling and exact
resource rules rather than accepting a partial or fuzzy host match.

- [ ] **Step 7: Run focused tests**

```bash
python -m stestr run mistral.tests.unit.actions.powerops.test_clients
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt mistral/actions/powerops/exceptions.py \
  mistral/actions/powerops/clients.py \
  mistral/tests/unit/actions/powerops/fakes.py \
  mistral/tests/unit/actions/powerops/test_clients.py
git commit -m "feat: add PowerOps OpenStack primitives"
```

---

### Task 3: Composite planned power-off and reboot actions

**Files:**
- Create: `mistral/actions/powerops/base.py`
- Create: `mistral/actions/powerops/planned.py`
- Test: `mistral/tests/unit/actions/powerops/test_planned.py`

**Interfaces:**
- Produces: `PowerOpsAction._run_locked(context, operation_name, operation)` template method.
- Produces: `PlannedPowerOffAction(host, segment_uuid, instance_policy="require_empty", allow_hard_off=False)`.
- Produces: `PlannedRebootAction(host, segment_uuid, instance_policy="require_empty", allow_hard_off=False)`.
- Returns: JSON-serializable dictionaries containing `host`, `operation`, `power_state`, `stopped_instance_ids`, `nova_enabled`, and `masakari_maintenance`.

- [ ] **Step 1: Write failing lock-lifetime and fail-safe tests**

```python
class PlannedPowerActionsTest(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.override_config("enabled", True, "powerops")
        self.override_config(
            "allowed_project_names", ["operations"], "powerops"
        )
        self.override_config(
            "allowed_user_names", ["powerops-operator"], "powerops"
        )

    def test_action_rejects_caller_outside_allowlists(self):
        self.override_config(
            "allowed_project_names", ["operations"], "powerops"
        )
        self.override_config(
            "allowed_user_names", ["powerops-operator"], "powerops"
        )
        action = planned.PlannedPowerOffAction(
            "compute-01", "segment-1", "require_empty", False
        )
        context = fakes.action_context(
            "execution-0", project_name="other", user_name="other"
        )
        self.assertRaises(
            exceptions.PowerOpsUnauthorized, action.run, context
        )

    @mock.patch.object(planned.coordination, "OperationCoordinator")
    @mock.patch.object(planned.clients, "CloudClients")
    @mock.patch.object(planned.clients, "connection_from_conf")
    def test_power_off_keeps_one_lock_for_complete_transition(
            self, connection_from_conf, cloud_cls, coordinator_cls):
        events = []
        coordinator_cls.return_value = fakes.recording_coordinator(events)
        cloud = cloud_cls.return_value
        cloud.resolve_host_set.side_effect = lambda *args: None
        cloud.set_masakari_maintenance.side_effect = (
            lambda *args: events.append("maintenance-true")
        )
        cloud.disable_nova.side_effect = (
            lambda *args: events.append("nova-disable")
        )
        cloud.apply_instance_policy.side_effect = lambda *args: (
            events.append("instances-stop"), ["vm-a"]
        )[1]
        cloud.assert_host_safe_for_power_off.side_effect = lambda *args: None
        cloud.power_off.side_effect = lambda *args: (
            events.extend(["power-off", "stable-off"]),
            fakes.node("n1", "compute-01", "power off"),
        )[1]
        action = planned.PlannedPowerOffAction(
            "compute-01", "segment-1", "stop", False
        )
        action._audit = mock.Mock(
            side_effect=lambda *args: events.append("audit-success")
        )

        result = action.run(fakes.action_context("execution-1"))

        self.assertEqual(
            ["coordinator-start", "host-lock-enter",
             "maintenance-true", "nova-disable", "instances-stop",
             "power-off", "stable-off", "audit-success",
             "host-lock-exit", "coordinator-stop"],
            events,
        )
        self.assertEqual(["vm-a"], result["stopped_instance_ids"])

    @mock.patch.object(planned.coordination, "OperationCoordinator")
    @mock.patch.object(planned.clients, "CloudClients")
    @mock.patch.object(planned.clients, "connection_from_conf")
    def test_reboot_failure_reasserts_disabled_and_maintenance(
            self, connection_from_conf, cloud_cls, coordinator_cls):
        events = []
        coordinator_cls.return_value = fakes.recording_coordinator(events)
        cloud = cloud_cls.return_value
        cloud.resolve_host_set.side_effect = lambda *args: None
        cloud.set_masakari_maintenance.side_effect = (
            lambda *args: events.append("maintenance-true")
        )
        cloud.disable_nova.side_effect = (
            lambda *args: events.append("nova-disable")
        )
        cloud.apply_instance_policy.return_value = []
        cloud.assert_host_safe_for_power_off.side_effect = lambda *args: None
        cloud.power_off.return_value = fakes.node(
            "n1", "compute-01", "power off"
        )
        cloud.power_on.side_effect = exceptions.PowerStateError(
            "power on failed"
        )
        action = planned.PlannedRebootAction(
            "compute-01", "segment-1", "require_empty", False
        )

        self.assertRaises(
            exceptions.PowerStateError,
            action.run,
            fakes.action_context("execution-2"),
        )
        self.assertEqual(
            ["maintenance-true", "nova-disable"],
            events[-2:],
        )
```

Use this test to prove `planned_reboot` starts only the UUIDs returned by its
own `stop` policy and does not require `stale_domains_checked`:

```python
@mock.patch.object(planned.coordination, "OperationCoordinator")
@mock.patch.object(planned.clients, "CloudClients")
@mock.patch.object(planned.clients, "connection_from_conf")
def test_reboot_restarts_only_its_stop_manifest(
        self, connection_from_conf, cloud_cls, coordinator_cls):
    events = []
    coordinator_cls.return_value = fakes.recording_coordinator(events)
    cloud = cloud_cls.return_value
    cloud.apply_instance_policy.return_value = ["vm-a", "vm-b"]
    cloud.power_off.return_value = fakes.node(
        "n1", "compute-01", "power off"
    )
    cloud.power_on.return_value = fakes.node(
        "n1", "compute-01", "power on"
    )
    cloud.start_instances.side_effect = lambda instance_ids: events.extend(
        [("start", instance_id) for instance_id in instance_ids]
    )
    action = planned.PlannedRebootAction(
        "compute-01", "segment-1", "stop", False
    )
    result = action.run(fakes.action_context("execution-2"))
    self.assertEqual(["vm-a", "vm-b"], result["stopped_instance_ids"])
    self.assertEqual(
        [("start", "vm-a"), ("start", "vm-b")],
        [event for event in events if event[0] == "start"],
    )
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m stestr run mistral.tests.unit.actions.powerops.test_planned
```

Expected: import failure for `mistral.actions.powerops.planned`.

- [ ] **Step 3: Implement the shared composite-action template**

```python
class PowerOpsAction(actions.Action):
    def _authorize(self, context):
        security = context.security
        if (
            security.project_name not in CONF.powerops.allowed_project_names
            or security.user_name not in CONF.powerops.allowed_user_names
        ):
            raise exceptions.PowerOpsUnauthorized(
                "caller is not authorized for PowerOps"
            )

    def _run_locked(self, context, operation_name, operation):
        if not CONF.powerops.enabled:
            raise exceptions.PowerOpsDisabled()
        self._authorize(context)
        execution_id = context.execution.action_execution_id
        cloud = clients.CloudClients(clients.connection_from_conf())
        with coordination.OperationCoordinator(execution_id) as coordinator:
            with coordinator.lock_host(self.host):
                self._nova_disabled = False
                try:
                    return operation(cloud)
                except Exception as exc:
                    fail_safe_errors = []
                    if self._nova_disabled:
                        fail_safe_errors = self._fail_safe(cloud)
                    try:
                        self._audit(
                            context,
                            operation_name,
                            "failure",
                            {
                                "error_type": type(exc).__name__,
                                "fail_safe_error_count": len(
                                    fail_safe_errors
                                ),
                            },
                        )
                    except Exception:
                        LOG.exception(
                            "Could not write PowerOps failure audit record"
                        )
                    raise

    def _fail_safe(self, cloud):
        errors = []
        for call in (
                lambda: cloud.set_masakari_maintenance(
                    self.segment_uuid, self.host, True),
                lambda: cloud.disable_nova(
                    self.host, CONF.powerops.nova_disable_reason)):
            try:
                call()
            except Exception as exc:
                errors.append(str(exc))
        return errors

    def _audit(self, context, operation, outcome, details):
        LOG.info(
            "PowerOps audit operation=%s outcome=%s host=%s "
            "workflow_execution_id=%s details=%s",
            operation, outcome, self.host,
            context.execution.workflow_execution_id, details,
        )
```

Immediately before calling `cloud.disable_nova()`, an operation sets
`self._nova_disabled = True`. This intentionally errs toward fail-safe: even
if the disable request returns an ambiguous transport error, the exception
path reasserts disabled/maintenance while the same host lock is still held.
Emit failure audit data without secrets before re-raising the original typed
exception. If `self._audit(context, operation, "success", result)` raises, the
same `_run_locked()` exception path reasserts the fail-safe state.

- [ ] **Step 4: Implement planned power-off**

The protected operation body is exactly:

```python
cloud.resolve_host_set(self.segment_uuid, self.host)
cloud.set_masakari_maintenance(self.segment_uuid, self.host, True)
self._nova_disabled = True
cloud.disable_nova(self.host, CONF.powerops.nova_disable_reason)
stopped = cloud.apply_instance_policy(self.host, self.instance_policy)
cloud.assert_host_safe_for_power_off(self.host)
node = cloud.power_off(self.host, self.allow_hard_off)
result = {
    "host": self.host,
    "operation": "planned_power_off",
    "power_state": node.power_state,
    "stopped_instance_ids": stopped,
    "nova_enabled": False,
    "masakari_maintenance": True,
}
self._audit(context, "planned_power_off", "success", result)
return result
```

`assert_host_safe_for_power_off()` re-lists the instances after policy
application and rejects any remaining instance for `require_empty`/`stop`; for
`live_migrate` it also rejects a server still reporting the source hypervisor.

- [ ] **Step 5: Implement planned reboot**

Use this complete protected body:

```python
cloud.resolve_host_set(self.segment_uuid, self.host)
cloud.set_masakari_maintenance(self.segment_uuid, self.host, True)
self._nova_disabled = True
cloud.disable_nova(self.host, CONF.powerops.nova_disable_reason)
stopped = cloud.apply_instance_policy(self.host, self.instance_policy)
cloud.assert_host_safe_for_power_off(self.host)
cloud.power_off(self.host, self.allow_hard_off)
cloud.power_on(self.host)
cloud.wait_nova_service(self.host, enabled=False, up=True)
cloud.start_instances(stopped)
cloud.enable_nova(self.host)
cloud.set_masakari_maintenance(self.segment_uuid, self.host, False)
result = {
    "host": self.host,
    "operation": "planned_reboot",
    "power_state": "power on",
    "stopped_instance_ids": stopped,
    "nova_enabled": True,
    "masakari_maintenance": False,
}
self._audit(context, "planned_reboot", "success", result)
return result
```

The health wait checks Nova service `state == "up"` while it is still
administratively disabled. `enable_nova()` occurs only after every manifest VM
has reached `ACTIVE`.

- [ ] **Step 6: Run focused tests**

```bash
python -m stestr run \
  mistral.tests.unit.actions.powerops.test_clients \
  mistral.tests.unit.actions.powerops.test_planned
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mistral/actions/powerops/base.py \
  mistral/actions/powerops/planned.py \
  mistral/tests/unit/actions/powerops/test_planned.py
git commit -m "feat: add planned host power actions"
```

---

### Task 4: Status and two-phase return-to-service actions

**Files:**
- Create: `mistral/actions/powerops/return_host.py`
- Test: `mistral/tests/unit/actions/powerops/test_return_host.py`

**Interfaces:**
- Produces: `HostPowerStatusAction(host, segment_uuid)` read-only action.
- Produces: `PowerOnForInspectionAction(host, segment_uuid)` mutating action.
- Produces: `ReturnToServiceAction(host, segment_uuid, stopped_instance_ids, stale_domains_checked=False)` mutating action.
- Preserves: Nova disabled and Masakari maintenance between the two mutating actions.

- [ ] **Step 1: Write failing phase-boundary tests**

```python
class ReturnHostActionsTest(base.BaseTest):
    def setUp(self):
        super().setUp()
        self.override_config("enabled", True, "powerops")
        self.override_config(
            "allowed_project_names", ["operations"], "powerops"
        )
        self.override_config(
            "allowed_user_names", ["powerops-operator"], "powerops"
        )

    @mock.patch.object(return_host.coordination, "OperationCoordinator")
    @mock.patch.object(return_host.clients, "CloudClients")
    @mock.patch.object(return_host.clients, "connection_from_conf")
    def test_power_on_for_inspection_keeps_host_out_of_service(
            self, connection_from_conf, cloud_cls, coordinator_cls):
        events = []
        coordinator_cls.return_value = fakes.recording_coordinator(events)
        cloud = cloud_cls.return_value
        cloud.set_masakari_maintenance.side_effect = (
            lambda *args: events.append("maintenance-true")
        )
        cloud.disable_nova.side_effect = (
            lambda *args: events.append("nova-disable")
        )
        cloud.power_on.side_effect = lambda *args: (
            events.append("power-on"),
            fakes.node("n1", "compute-01", "power on"),
        )[1]
        cloud.wait_nova_service.side_effect = lambda *args, **kwargs: None
        action = return_host.PowerOnForInspectionAction(
            "compute-01", "segment-1"
        )
        result = action.run(fakes.action_context("execution-3"))
        self.assertEqual("power on", result["power_state"])
        self.assertFalse(result["nova_enabled"])
        self.assertTrue(result["masakari_maintenance"])
        self.assertNotIn("nova-enable", events)
        self.assertNotIn("maintenance-false", events)

    def test_return_rejects_missing_post_inspection_assertion(self):
        action = return_host.ReturnToServiceAction(
            "compute-01", "segment-1", ["vm-a"], False
        )
        self.assertRaises(
            exceptions.OperatorGateRequired,
            action.run,
            fakes.action_context("execution-4"),
        )

    @mock.patch.object(return_host.coordination, "OperationCoordinator")
    @mock.patch.object(return_host.clients, "CloudClients")
    @mock.patch.object(return_host.clients, "connection_from_conf")
    def test_return_starts_manifest_before_enabling_host(
            self, connection_from_conf, cloud_cls, coordinator_cls):
        events = []
        coordinator_cls.return_value = fakes.recording_coordinator(events)
        cloud = cloud_cls.return_value
        cloud.require_stable_power_on.side_effect = lambda *args: None
        cloud.wait_nova_service.side_effect = lambda *args, **kwargs: None
        cloud.require_masakari_maintenance.side_effect = lambda *args: None
        cloud.start_instances.side_effect = lambda instance_ids: events.extend(
            [("start", instance_id) for instance_id in sorted(instance_ids)]
        )
        cloud.enable_nova.side_effect = (
            lambda *args: events.append("nova-enable")
        )
        cloud.set_masakari_maintenance.side_effect = (
            lambda *args: events.append("maintenance-false")
        )
        action = return_host.ReturnToServiceAction(
            "compute-01", "segment-1", ["vm-b", "vm-a"], True
        )
        action.run(fakes.action_context("execution-5"))
        self.assertLess(events.index(("start", "vm-a")),
                        events.index("nova-enable"))
        self.assertLess(events.index(("start", "vm-b")),
                        events.index("nova-enable"))
        self.assertLess(events.index("nova-enable"),
                        events.index("maintenance-false"))
```

Use this test to prove `HostPowerStatusAction` creates no coordinator and
issues no mutating API call:

```python
@mock.patch.object(return_host.coordination, "OperationCoordinator")
@mock.patch.object(return_host.clients, "CloudClients")
@mock.patch.object(return_host.clients, "connection_from_conf")
def test_status_is_read_only(
        self, connection_from_conf, cloud_cls, coordinator_cls):
    events = []
    cloud = cloud_cls.return_value
    cloud.ironic_node.return_value = fakes.node(
        "n1", "compute-01", "power on"
    )
    cloud.nova_service.return_value = fakes.service(
        "s1", "compute-01", state="up", is_disabled=True
    )
    cloud.masakari_host.return_value = fakes.masakari_host(
        "h1", "compute-01", on_maintenance=True
    )
    action = return_host.HostPowerStatusAction("compute-01", "segment-1")
    result = action.run(fakes.action_context("execution-6"))
    coordinator_cls.assert_not_called()
    self.assertEqual("compute-01", result["host"])
    cloud.disable_nova.assert_not_called()
    cloud.enable_nova.assert_not_called()
    cloud.set_masakari_maintenance.assert_not_called()
    cloud.power_off.assert_not_called()
    cloud.power_on.assert_not_called()
```

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m stestr run mistral.tests.unit.actions.powerops.test_return_host
```

Expected: import failure for `mistral.actions.powerops.return_host`.

- [ ] **Step 3: Implement read-only status**

Resolve the exact Ironic Node, Nova service and Masakari host, then return:

```python
return {
    "host": self.host,
    "ironic_node_uuid": node.id,
    "power_state": node.power_state,
    "target_power_state": node.target_power_state,
    "ironic_last_error": node.last_error,
    "nova_enabled": not service.is_disabled,
    "nova_state": service.state,
    "masakari_maintenance": masakari_host.on_maintenance,
}
```

Status first rejects `CONF.powerops.enabled == false`, then calls
`_authorize(context)`, but does not acquire a lock because it never mutates
state. Its result is a point-in-time observation, which the Russian runbook
must state explicitly.

- [ ] **Step 4: Implement power-on-for-inspection**

Use this `_run_locked()` operation body:

```python
cloud.resolve_host_set(self.segment_uuid, self.host)
cloud.set_masakari_maintenance(self.segment_uuid, self.host, True)
self._nova_disabled = True
cloud.disable_nova(self.host, CONF.powerops.nova_disable_reason)
node = cloud.power_on(self.host)
cloud.wait_nova_service(self.host, enabled=False, up=True)
result = {
    "host": self.host,
    "operation": "power_on_for_inspection",
    "power_state": node.power_state,
    "stopped_instance_ids": [],
    "nova_enabled": False,
    "masakari_maintenance": True,
}
self._audit(context, "power_on_for_inspection", "success", result)
return result
```

- [ ] **Step 5: Implement return-to-service**

Validate the gate before creating a coordinator:

```python
if self.stale_domains_checked is not True:
    raise exceptions.OperatorGateRequired(
        "resume with env stale_domains_checked=true after host inspection"
    )
if len(set(self.stopped_instance_ids)) != len(self.stopped_instance_ids):
    raise exceptions.InstanceManifestError("duplicate instance UUID")
```

Use this body under the new host lock:

```python
self._nova_disabled = True
cloud.require_stable_power_on(self.host)
cloud.wait_nova_service(self.host, enabled=False, up=True)
cloud.require_masakari_maintenance(
    self.segment_uuid, self.host, expected=True
)
cloud.start_instances(self.stopped_instance_ids)
cloud.enable_nova(self.host)
cloud.set_masakari_maintenance(self.segment_uuid, self.host, False)
result = {
    "host": self.host,
    "operation": "return_to_service",
    "power_state": "power on",
    "stopped_instance_ids": sorted(self.stopped_instance_ids),
    "nova_enabled": True,
    "masakari_maintenance": False,
}
self._audit(context, "return_to_service", "success", result)
return result
```

Any failure, including one after `enable_nova()`, invokes `_fail_safe()` under
the still-owned lock and re-disables Nova before exit.

- [ ] **Step 6: Run all PowerOps action tests**

```bash
python -m stestr run mistral.tests.unit.actions.powerops
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mistral/actions/powerops/return_host.py \
  mistral/tests/unit/actions/powerops/test_return_host.py
git commit -m "feat: add guarded host return actions"
```

---

### Task 5: Register actions and ship the workbook contract

**Files:**
- Modify: `setup.cfg`
- Create: `etc/mistral/power_ops.yaml`
- Create: `releasenotes/notes/powerops-planned-host-actions.yaml`
- Test: `mistral/tests/unit/actions/powerops/test_registration.py`
- Test: `mistral/tests/unit/actions/powerops/test_workbook.py`

**Interfaces:**
- Produces actions: `powerops.host_power_status`, `powerops.planned_power_off`, `powerops.planned_reboot`, `powerops.power_on_for_inspection`, `powerops.return_to_service`.
- Produces workflows: `power_ops.host_power_status`, `power_ops.planned_power_off`, `power_ops.planned_reboot`, `power_ops.power_on_and_return`.
- Consumes on resume: workflow environment key `stale_domains_checked` with Boolean value `true`.

- [ ] **Step 1: Write failing registration and workbook parser tests**

```python
EXPECTED_ACTIONS = {
    "powerops.host_power_status",
    "powerops.planned_power_off",
    "powerops.planned_reboot",
    "powerops.power_on_for_inspection",
    "powerops.return_to_service",
}


def test_powerops_entry_points_are_complete(self):
    names = {
        entry.name
        for entry in importlib.metadata.entry_points(
            group="mistral.actions"
        )
    }
    self.assertTrue(EXPECTED_ACTIONS.issubset(names))


def test_workbook_parses_and_has_operator_pause(self):
    definition = pathlib.Path("etc/mistral/power_ops.yaml").read_text()
    spec = parser.get_workbook_spec_from_yaml(definition)
    workflow = spec.get_workflows()["power_on_and_return"]
    gate = workflow.get_tasks()["operator_inspection_gate"]
    self.assertTrue(gate.get_policies().get_pause_before())
```

Also load the YAML as a dictionary and assert that no task action name contains
`evacuate`, the return task reads `env().stale_domains_checked`, and no lock
action is exposed as a separate workflow task.

- [ ] **Step 2: Run tests and verify RED**

```bash
python -m stestr run \
  mistral.tests.unit.actions.powerops.test_registration \
  mistral.tests.unit.actions.powerops.test_workbook
```

Expected: missing entry points and workbook file.

- [ ] **Step 3: Register the five action entry points**

Add under `mistral.actions`:

```ini
powerops.host_power_status = mistral.actions.powerops.return_host:HostPowerStatusAction
powerops.planned_power_off = mistral.actions.powerops.planned:PlannedPowerOffAction
powerops.planned_reboot = mistral.actions.powerops.planned:PlannedRebootAction
powerops.power_on_for_inspection = mistral.actions.powerops.return_host:PowerOnForInspectionAction
powerops.return_to_service = mistral.actions.powerops.return_host:ReturnToServiceAction
```

- [ ] **Step 4: Create the complete workbook**

Use this DSL structure; preserve the exact public inputs and action names:

```yaml
---
version: '2.0'
name: power_ops

workflows:
  host_power_status:
    input:
      - host
      - segment_uuid
    tasks:
      status:
        action: powerops.host_power_status
        input:
          host: <% $.host %>
          segment_uuid: <% $.segment_uuid %>
        publish:
          result: <% task().result %>
    output:
      result: <% $.result %>

  planned_power_off:
    input:
      - host
      - segment_uuid
      - instance_policy: require_empty
      - allow_hard_off: false
    tasks:
      power_off:
        action: powerops.planned_power_off
        input:
          host: <% $.host %>
          segment_uuid: <% $.segment_uuid %>
          instance_policy: <% $.instance_policy %>
          allow_hard_off: <% $.allow_hard_off %>
        publish:
          result: <% task().result %>
    output:
      result: <% $.result %>
      stopped_instance_ids: <% $.result.stopped_instance_ids %>

  planned_reboot:
    input:
      - host
      - segment_uuid
      - instance_policy: require_empty
      - allow_hard_off: false
    tasks:
      reboot:
        action: powerops.planned_reboot
        input:
          host: <% $.host %>
          segment_uuid: <% $.segment_uuid %>
          instance_policy: <% $.instance_policy %>
          allow_hard_off: <% $.allow_hard_off %>
        publish:
          result: <% task().result %>
    output:
      result: <% $.result %>

  power_on_and_return:
    input:
      - host
      - segment_uuid
      - stopped_instance_ids: []
    tasks:
      power_on_for_inspection:
        action: powerops.power_on_for_inspection
        input:
          host: <% $.host %>
          segment_uuid: <% $.segment_uuid %>
        on-success: operator_inspection_gate

      operator_inspection_gate:
        action: std.noop
        pause-before: true
        on-success: return_to_service

      return_to_service:
        action: powerops.return_to_service
        input:
          host: <% $.host %>
          segment_uuid: <% $.segment_uuid %>
          stopped_instance_ids: <% $.stopped_instance_ids %>
          stale_domains_checked: <% env().get('stale_domains_checked', false) %>
        publish:
          result: <% task().result %>
    output:
      result: <% $.result %>
```

The operator resume request must use this body:

```json
{
  "state": "RUNNING",
  "params": {
    "env": {
      "stale_domains_checked": true
    }
  }
}
```

- [ ] **Step 5: Add the release note and run registration tests**

Document that actions are inert until invoked, PowerOps is disabled by
default, resume must carry the operator gate environment value, and deploy
registration is handled by Kolla-Ansible.

```bash
python -m stestr run \
  mistral.tests.unit.actions.powerops.test_registration \
  mistral.tests.unit.actions.powerops.test_workbook
```

Expected: PASS.

- [ ] **Step 6: Run the complete repository verification**

```bash
tox -e py3
tox -e pep8
git diff --check stable/2025.1...HEAD
rg -n "evacuat" mistral/actions/powerops etc/mistral/power_ops.yaml
```

Expected: both tox environments pass and the final search has no matches.

- [ ] **Step 7: Commit and export the patch series**

```bash
git add setup.cfg etc/mistral/power_ops.yaml \
  releasenotes/notes/powerops-planned-host-actions.yaml \
  mistral/tests/unit/actions/powerops
git commit -m "feat: register the PowerOps workbook API"
POWEROPS_ARTIFACT_ROOT=/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches
git format-patch --output-directory \
  "$POWEROPS_ARTIFACT_ROOT/patches/mistral" stable/2025.1..HEAD
git worktree add /tmp/mistral-powerops-apply stable/2025.1
git -C /tmp/mistral-powerops-apply am \
  "$POWEROPS_ARTIFACT_ROOT"/patches/mistral/*.patch
git -C /tmp/mistral-powerops-apply diff --check stable/2025.1...HEAD
```

Expected: every patch applies in order without fuzz or rejects.
