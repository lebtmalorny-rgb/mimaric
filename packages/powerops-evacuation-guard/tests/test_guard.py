"""Assertions catch missing durable ownership/CAS/claim checks, not fake counters."""
import uuid
import pytest
import requests


def uid(n):
    return str(uuid.UUID(int=n))


def register(g, n, target=1, request_id=None):
    return g.register(uid(n), uid(100+n), 'src', uid(200+target),
                      'dst-' + str(target), uid(300+n), request_id)


def proof(n, target=1):
    return dict(migration_status='done', vm_uuid=uid(100+n),
                target_uuid=uid(200+target), target_host='dst-'+str(target),
                vm_state='active', task_state=None)


def errors():
    from powerops_evacuation_guard import GuardBusy, GuardDuplicate, GuardConflict, GuardDenied, GuardUnavailable
    return GuardBusy, GuardDuplicate, GuardConflict, GuardDenied, GuardUnavailable


def test_same_target_serial_different_targets_overlap_and_global_bound(guard):
    Busy, *_ = errors()
    register(guard, 1)
    assert guard.try_admit(uid(1), uid(301))['state'] == 'RUNNING'
    register(guard, 2)
    with pytest.raises(Busy):
        guard.try_admit(uid(2), uid(302))
    assert guard.get_operation(uid(2))['state'] == 'WAITING'
    for n in (3, 4):
        register(guard, n, n)
        assert guard.try_admit(uid(n), uid(300+n))['state'] == 'RUNNING'
    register(guard, 5, 5)
    with pytest.raises(Busy):
        guard.try_admit(uid(5), uid(305))


def test_duplicates_and_stale_owners_cannot_execute_or_complete(guard, factory):
    _, Duplicate, Conflict, Denied, _ = errors()
    register(guard, 1)
    guard.try_admit(uid(1), uid(301))
    with pytest.raises(Duplicate):
        register(factory(), 1)
    with pytest.raises(Duplicate):
        factory().try_admit(uid(1), uid(301))
    with pytest.raises((Conflict, Denied)):
        guard.complete(uid(1), uid(900), proof(1))
    guard.complete(uid(1), uid(301), proof(1))
    assert guard.finish_cooldown(uid(1), uid(301))['state'] == 'DONE'
    with pytest.raises(Duplicate):
        register(guard, 1)


def test_intent_reserves_vm_and_request_and_binds_only_matching_identity(guard):
    _, Duplicate, Conflict, Denied, _ = errors()
    req = 'req-' + uid(501)
    guard.create_intent(uid(401), uid(101), 'src', req, 'masakari')
    with pytest.raises(Duplicate):
        guard.create_intent(uid(402), uid(101), 'src', 'req-'+uid(502), 'masakari')
    with pytest.raises((Conflict, Denied)):
        register(guard, 2, request_id=req)
    with pytest.raises((Conflict, Denied)):
        register(guard, 1)
    op = register(guard, 1, request_id=req)
    assert op['attempt_uuid'] == uid(401)
    assert guard.get_intent(uid(401))['migration_uuid'] == uid(1)
    guard.try_admit(uid(1), uid(301))
    guard.note_intent_unknown(uid(401), 'API timeout')
    assert guard.get_operation(uid(1))['state'] == 'RUNNING'
    assert guard.get_intent(uid(401))['observation'] == 'UNKNOWN'


def test_unknown_unbound_intent_allows_delayed_bind_but_resolved_never_does(guard):
    _, Duplicate, Conflict, Denied, _ = errors()
    req = 'req-'+uid(501)
    guard.create_intent(uid(401), uid(101), 'src', req, 'masakari')
    intent = guard.note_intent_unknown(uid(401), 'timeout')
    assert register(guard, 1, request_id=req)['state'] == 'WAITING'
    with pytest.raises(Conflict):
        guard.resolve_intent(uid(401), intent['revision'], 'operator', 'checked', True, True)
    req2 = 'req-'+uid(502)
    intent = guard.create_intent(uid(402), uid(102), 'src', req2, 'masakari')
    resolved = guard.resolve_intent(uid(402), intent['revision'], 'op', 'checked', True, True)
    assert resolved['state'] == 'RESOLVED'
    with pytest.raises((Duplicate, Denied)):
        register(guard, 2, request_id=req2)


def test_denial_releases_only_waiting_vm_and_retains_tombstone(guard):
    _, Duplicate, *_ = errors()
    register(guard, 1)
    assert guard.deny_waiting(uid(1), uid(301), 'deadline')['state'] == 'DENIED'
    with pytest.raises(Duplicate):
        guard.try_admit(uid(1), uid(301))
    assert guard.register(uid(2), uid(101), 'src', uid(201), 'dst-1', uid(302))['state'] == 'WAITING'


def test_complete_demands_exact_terminal_proof_and_keeps_claims(guard):
    Busy, _, _, Denied, _ = errors()
    register(guard, 1)
    guard.try_admit(uid(1), uid(301))
    for patch in ({'migration_status':'running'}, {'vm_uuid':uid(999)},
                  {'target_host':'other'}, {'target_uuid':uid(999)},
                  {'vm_state':'error'}, {'task_state':'rebuilding'}):
        with pytest.raises(Denied):
            guard.complete(uid(1), uid(301), dict(proof(1), **patch))
    guard.complete(uid(1), uid(301), proof(1))
    register(guard, 2)
    with pytest.raises(Busy):
        guard.try_admit(uid(2), uid(302))
    guard.finish_cooldown(uid(1), uid(301))
    assert guard.try_admit(uid(2), uid(302))['state'] == 'RUNNING'


def test_unknown_retains_capacity_and_requires_exact_boolean_proof(guard):
    Busy, _, Conflict, Denied, _ = errors()
    register(guard, 1)
    guard.try_admit(uid(1), uid(301))
    op = guard.mark_unknown(uid(1), uid(301), 'lost executor')
    register(guard, 2)
    with pytest.raises(Busy):
        guard.try_admit(uid(2), uid(302))
    for args in ((False, True), (True, False), (1, True), ('true', True)):
        with pytest.raises(Denied):
            guard.resolve(uid(1), op['revision'], 'op', 'verified', *args)
    with pytest.raises(Conflict):
        guard.resolve(uid(1), op['revision']-1, 'op', 'verified', True, True)
    assert guard.resolve(uid(1), op['revision'], 'op', 'verified', True, True)['state'] == 'DONE'
    assert guard.try_admit(uid(2), uid(302))['state'] == 'RUNNING'


def test_cooldown_monotonic_recovery_and_old_finisher_cannot_release(factory, monkeypatch):
    from powerops_evacuation_guard import guard as module
    _, _, Conflict, Denied, _ = errors()
    now = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(module.time, 'sleep', lambda delay: now.__setitem__(0, now[0]+delay))
    monkeypatch.setattr(module.time, 'time', lambda: -100000000.0)
    g = factory(cooldown=5)
    g.initialize('test', 'test')
    register(g, 1)
    g.try_admit(uid(1), uid(301))
    op = g.complete(uid(1), uid(301), proof(1))
    restarted = factory(cooldown=5)
    with pytest.raises((Conflict, Denied)):
        restarted.finish_cooldown(uid(1), uid(301))
    now[0] += 100
    assert restarted.recover_cooldown(uid(1), op['revision'], 'operator', 'recovery')['state'] == 'DONE'
    assert now[0] == 105
    register(g, 2)
    g.try_admit(uid(2), uid(302))
    with pytest.raises((Conflict, Denied)):
        g.finish_cooldown(uid(1), uid(301))
    assert g.get_operation(uid(2))['state'] == 'RUNNING'


def test_configure_requires_empty_claim_range_and_runtime_agreement(guard, factory):
    _, _, Conflict, Denied, _ = errors()
    old = guard.configuration()
    register(guard, 1)
    with pytest.raises((Conflict, Denied)):
        guard.configure(old['revision'], 4, 0, 'op', 'change')
    guard.deny_waiting(uid(1), uid(301), 'stop')
    conf = guard.configure(old['revision'], 4, 0, 'op', 'change')
    assert conf['max_parallel'] == 4
    with pytest.raises((Conflict, Denied)):
        register(guard, 2)
    assert guard.status()['configuration']['max_parallel'] == 4
    assert register(factory(max_parallel=4), 2)['state'] == 'WAITING'


def test_status_pagination_keeps_each_record_once(guard):
    for n in range(1, 8):
        register(guard, n)
    records, cursor = [], None
    while True:
        page = guard.status(limit=2, cursor=cursor)
        assert len(page['records']) <= 2
        records.extend(page['records'])
        cursor = page['cursor']
        if cursor is None:
            break
    assert {r['migration_uuid'] for r in records if r.get('kind') == 'operation'} == {uid(n) for n in range(1, 8)}


def test_lost_successful_admit_response_does_not_enable_second_execution(guard, factory, backend):
    if backend is None:
        pytest.skip('Transport ambiguity injected at the HTTP boundary in offline suite')
    _, Duplicate, _, _, Unavailable = errors()
    register(guard, 1)
    def lose():
        raise requests.ConnectionError('secret https://user:password@host')
    backend.after_txn = lose
    with pytest.raises(Unavailable):
        guard.try_admit(uid(1), uid(301))
    assert factory().get_operation(uid(1))['state'] == 'RUNNING'
    with pytest.raises(Duplicate):
        factory().try_admit(uid(1), uid(301))


@pytest.mark.parametrize('race', ['deny', 'intent', 'configure'])
def test_transaction_races_have_one_winner(guard, backend, race):
    if backend is None:
        pytest.skip('Deterministic interleave uses HTTP boundary fake')
    _, _, Conflict, Denied, _ = errors()
    if race == 'deny':
        register(guard, 1)
        backend.before_txn = lambda: guard.try_admit(uid(1), uid(301))
        with pytest.raises((Conflict, Denied)):
            guard.deny_waiting(uid(1), uid(301), 'timeout')
        assert guard.get_operation(uid(1))['state'] == 'RUNNING'
    elif race == 'intent':
        req = 'req-'+uid(501)
        intent = guard.create_intent(uid(401), uid(101), 'src', req, 'masakari')
        backend.before_txn = lambda: register(guard, 1, request_id=req)
        with pytest.raises(Conflict):
            guard.resolve_intent(uid(401), intent['revision'], 'op', 'done', True, True)
        assert guard.get_intent(uid(401))['migration_uuid'] == uid(1)
        assert guard.try_admit(uid(1), uid(301))['state'] == 'RUNNING'
    else:
        config = guard.configuration()
        backend.before_txn = lambda: register(guard, 1)
        with pytest.raises(Conflict):
            guard.configure(config['revision'], 4, 0, 'op', 'change')
        assert guard.configuration()['max_parallel'] == 3


def test_normal_finisher_waits_full_cooldown_despite_forward_wall_clock(factory, monkeypatch):
    from powerops_evacuation_guard import guard as module
    now = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(module.time, 'time', lambda: 10**15)
    monkeypatch.setattr(module.time, 'sleep', lambda delay: now.__setitem__(0, now[0]+delay))
    g = factory(cooldown=5)
    g.initialize('op', 'test')
    register(g, 1)
    g.try_admit(uid(1), uid(301))
    g.complete(uid(1), uid(301), proof(1))
    now[0] = 2
    g.finish_cooldown(uid(1), uid(301))
    assert now[0] == 5


def test_lost_intent_creation_response_cannot_authorize_resubmission(guard, backend):
    if backend is None:
        pytest.skip('Response loss injected at HTTP boundary')
    _, Duplicate, _, _, Unavailable = errors()
    def lose():
        raise requests.Timeout('sensitive exception')
    backend.after_txn = lose
    with pytest.raises(Unavailable):
        guard.create_intent(uid(401), uid(101), 'src', 'req-'+uid(501), 'masakari')
    with pytest.raises(Duplicate):
        guard.create_intent(uid(401), uid(101), 'src', 'req-'+uid(501), 'masakari')
    assert register(guard, 1, request_id='req-'+uid(501))['attempt_uuid'] == uid(401)


def test_observer_does_not_overwrite_cooldown_or_done(guard):
    guard.create_intent(uid(401), uid(101), 'src', 'req-'+uid(501), 'masakari')
    register(guard, 1, request_id='req-'+uid(501))
    guard.try_admit(uid(1), uid(301))
    guard.complete(uid(1), uid(301), proof(1))
    guard.note_intent_unknown(uid(401), 'late timeout')
    assert guard.get_operation(uid(1))['state'] == 'COOLDOWN'
    guard.finish_cooldown(uid(1), uid(301))
    guard.note_intent_unknown(uid(401), 'later timeout')
    assert guard.get_operation(uid(1))['state'] == 'DONE'


def test_resolve_wins_before_delayed_bind_transaction(guard, backend):
    if backend is None:
        pytest.skip('Deterministic interleave uses HTTP boundary fake')
    _, _, Conflict, _, _ = errors()
    intent = guard.create_intent(uid(401), uid(101), 'src', 'req-'+uid(501), 'masakari')
    backend.before_txn = lambda: guard.resolve_intent(uid(401), intent['revision'], 'op', 'checked', True, True)
    with pytest.raises(Conflict):
        register(guard, 1, request_id='req-'+uid(501))
    assert guard.get_intent(uid(401))['state'] == 'RESOLVED'


def test_running_resolution_requires_full_cooldown(factory, monkeypatch):
    from powerops_evacuation_guard import guard as module
    now = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(module.time, 'sleep', lambda delay: now.__setitem__(0, now[0]+delay))
    g = factory(cooldown=5)
    g.initialize('op', 'test')
    register(g, 1)
    op = g.try_admit(uid(1), uid(301))
    assert g.resolve(uid(1), op['revision'], 'op', 'terminal and quiesced', True, True)['state'] == 'DONE'
    assert now[0] == 5


def test_waiting_resolution_denies_and_stale_executor_never_admits(guard):
    _, Duplicate, Conflict, *_ = errors()
    op = register(guard, 1)
    result = guard.resolve(uid(1), op['revision'], 'op', 'cancelled and quiesced', True, True)
    assert result['state'] == 'DENIED'
    with pytest.raises((Duplicate, Conflict)):
        guard.try_admit(uid(1), uid(301))


def test_recovery_audits_actor_without_fabricating_resolution(guard, factory):
    register(guard, 1)
    guard.try_admit(uid(1), uid(301))
    op = guard.complete(uid(1), uid(301), proof(1))
    result = factory().recover_cooldown(uid(1), op['revision'], 'recovery-op', 'restart')
    assert result['recovery'] == {'actor': 'recovery-op', 'reason': 'restart'}
    assert result['resolution'] is None


def test_reinitialization_does_not_reset_existing_claims(guard):
    _, _, Conflict, *_ = errors()
    register(guard, 1)
    guard.try_admit(uid(1), uid(301))
    with pytest.raises(Conflict):
        guard.initialize('op', 'reset attempt')
    assert guard.get_operation(uid(1))['state'] == 'RUNNING'


def test_status_exposes_integer_read_revision(guard):
    initial = guard.configuration()['revision']
    register(guard, 1)
    older = register(guard, 2)
    latest = guard.try_admit(uid(1), uid(301))
    result = guard.status(limit=2)
    assert type(result.get('revision')) is int
    assert result['revision'] >= latest['revision'] > older['revision'] > initial
    assert [record['revision'] for record in result['records']] == [latest['revision'], older['revision']]


@pytest.mark.parametrize('malformation', ['resolved_without_proof', 'submitting_with_resolution'])
def test_inconsistent_intent_state_is_not_a_binding_authority(guard, backend, malformation):
    if backend is None:
        pytest.skip('Stored corruption injected at HTTP boundary')
    import base64
    import json
    _, _, _, _, Unavailable = errors()
    guard.create_intent(uid(401), uid(101), 'src', 'req-'+uid(501), 'masakari')
    record = backend.data[(guard.prefix+'/records/intents/'+uid(401)).encode()]
    value = json.loads(base64.b64decode(record['value']))
    if malformation == 'resolved_without_proof':
        value['state'] = 'RESOLVED'
    else:
        value['resolution'] = dict(actor='op', reason='terminal', nova_terminal=True, executors_quiesced=True)
    record['value'] = base64.b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(Unavailable):
        guard.get_intent(uid(401))
