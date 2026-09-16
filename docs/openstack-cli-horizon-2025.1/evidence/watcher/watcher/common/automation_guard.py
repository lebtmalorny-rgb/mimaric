# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Scheduled automation admission and immutable action-plan provenance."""
import inspect
import uuid

from powerops_watcher_guard import config
from powerops_watcher_guard.gate import GuardDenied

from watcher import conf
from watcher import objects


MANUAL = 'manual'


def enabled():
    return conf.CONF.watcher_automation_guard.enabled


def validate_epoch(epoch):
    if not enabled():
        return
    if epoch == MANUAL:
        return
    try:
        valid = isinstance(epoch, str) and str(uuid.UUID(epoch)) == epoch
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise GuardDenied(
            'Unclassified action plan; recompute before applying')
    config.from_conf(conf.CONF).admit(expected_epoch=epoch)


def admit_audit(audit):
    if not enabled():
        return None
    if audit.audit_type in ('ONESHOT', 'EVENT'):
        return MANUAL
    if audit.audit_type != 'CONTINUOUS':
        raise GuardDenied('Unclassified audit type')
    return config.from_conf(conf.CONF).admit()


def validate_plan(plan):
    if enabled():
        try:
            epoch = plan.automation_epoch
        except (AttributeError, NotImplementedError):
            epoch = None
        validate_epoch(epoch)


def validate_action(context, action):
    if enabled():
        validate_plan(objects.ActionPlan.get_by_id(context,
                                                   action.action_plan_id))


def schedule(planner, context, audit_id, solution, epoch):
    # Reject old plugin signatures BEFORE invoking potentially effectful code.
    try:
        inspect.signature(planner.schedule).bind(
            context, audit_id, solution, automation_epoch=epoch)
    except (TypeError, ValueError):
        raise GuardDenied('Planner must support automation_epoch') from None
    validate_epoch(epoch)
    plan = planner.schedule(
        context, audit_id, solution, automation_epoch=epoch)
    if getattr(plan, 'automation_epoch', None) != epoch:
        raise GuardDenied('Planner did not preserve automation provenance')
    return plan


def fresh_model(collector, epoch):
    if not enabled() or epoch in (None, MANUAL):
        return collector.get_latest_cluster_data_model()
    # The same lock covers normal background synchronize, its entire build,
    # and the deep copy. Pre-hold builds cannot overwrite our refresh.
    with collector.lock:
        validate_epoch(epoch)
        try:
            if getattr(collector, '_automation_epoch', None) != epoch:
                collector.synchronize()
                validate_epoch(epoch)
            model = collector.get_latest_cluster_data_model()
            if model is None or model.stale:
                raise GuardDenied('Fresh cluster model is unavailable')
            collector._automation_epoch = epoch
        except GuardDenied:
            collector._automation_epoch = None
            raise
        except Exception:
            collector._automation_epoch = None
            raise GuardDenied(
                'Cluster model refresh failed; retry next tick') from None
        validate_epoch(epoch)
        return model


def scoped_model(collector, audit_scope, epoch):
    # Scope selection can invalidate the collector cache. Serialize it with
    # background builds and the snapshot for this invocation, including manual
    # consumers of the same collector. Never share a mutable scope handler.
    guarded = enabled() and epoch not in (None, MANUAL)
    with collector.lock:
        try:
            handler = collector.get_audit_scope_handler(
                audit_scope=audit_scope)
            model = handler.get_scoped_model(fresh_model(collector, epoch))
            if guarded:
                validate_epoch(epoch)
            return model
        except GuardDenied:
            raise
        except Exception:
            if not guarded:
                raise
            raise GuardDenied(
                'Model scope refresh failed; retry next tick') from None
