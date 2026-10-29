"""Offline ledger behavior; SQLite results are not MySQL concurrency evidence."""

import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from app.agent_schemas import OwnerContext
from app.gateway_contracts import Authorization, ToolResponse
from app.models import AuditEvent, GatewayOperation, GatewayTask, ScopedConsent
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    validate_agent_credential,
)
from app.services.operation_ledger import (
    OperationError,
    admit_operation,
    get_operation_status,
    request_digests,
    validate_future_dispatch,
    validate_transition,
)
from app.services.resource_catalog import CatalogResource, ResourceCatalog
from app.services.scoped_consent import record_decision, revoke_scoped_consent
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable
from tests.test_scoped_consent import (
    CATALOG,
    NOW,
    OWNER,
    PIN,
    SCOPE,
    grant,
    request_for,
)
from tests.test_scoped_consent import gateway as _gateway
from tests.test_scoped_consent import member_b_contract as _member_b_contract

gateway = _gateway
member_b_contract = _member_b_contract


def admit(gateway, *, now=NOW, **changes):
    factory, task, issued, _ = gateway
    with factory() as db:
        return admit_operation(
            db, token=issued.token, request=request_for(task, **changes), catalog=CATALOG, now=now
        )


def operations(gateway):
    with gateway[0]() as db:
        return list(db.scalars(select(GatewayOperation)))


def status(gateway):
    factory, _, issued, _ = gateway
    with factory() as db:
        return get_operation_status(db, token=issued.token, request_id="req_scoped", now=NOW)


def new_binding(gateway, owner=OWNER):
    factory = gateway[0]
    catalog = ResourceCatalog(
        resources=(CatalogResource(**PIN.model_dump(), owner_id=owner.owner_id),)
    )
    with factory() as db:
        task = create_trusted_task(
            db,
            owner=owner,
            scope=SCOPE,
            catalog=catalog,
            expires_at=NOW + timedelta(hours=1),
            now=NOW,
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    return task, issued, catalog


def test_new_reservation_and_exact_replay(gateway, member_b_contract):
    grant(gateway)
    first = admit(gateway)
    second = admit(gateway)
    assert first == second and first.decision == "ALLOW"
    assert first.execution_status == "NOT_EXECUTED"
    assert first.request_id == "req_scoped" and first.result is first.approval_ref is None
    rows = operations(gateway)
    assert len(rows) == 1 and rows[0].operation_status == "ADMITTED"
    assert rows[0].execution_started_at is rows[0].execution_finished_at is None
    assert rows[0].audit_event_ref == first.audit_event_ref
    parsed = member_b_contract.ToolResponse.model_validate_json(first.model_dump_json())
    assert parsed.request_id == "req_scoped"


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "req_other"},
        {"arguments": {"resource_id": "resource_other"}},
        {"idempotency_key": "key_other"},
        {"purpose": "answer_question"},
    ],
)
def test_conflicting_replay_never_aliases(gateway, changes):
    admit(gateway)
    before = operations(gateway)[0]
    with pytest.raises(OperationError) as error:
        admit(gateway, **changes)
    assert error.value.status_code == 409 and error.value.code == "IDEMPOTENCY_CONFLICT"
    after = operations(gateway)
    assert len(after) == 1 and after[0].operation_ref == before.operation_ref
    assert after[0].canonical_request_digest == before.canonical_request_digest


def test_new_ids_cannot_duplicate_wire_operation(gateway):
    admit(gateway)
    with pytest.raises(OperationError, match="LOGICAL_OPERATION_EXISTS"):
        admit(gateway, request_id="req_other", idempotency_key="key_other")
    assert len(operations(gateway)) == 1


@pytest.mark.parametrize("other_owner", [False, True])
def test_scoped_keys_and_request_id_owner_scope(gateway, other_owner):
    admit(gateway)
    owner = OwnerContext(owner_id="other-owner") if other_owner else OWNER
    task, issued, catalog = new_binding(gateway, owner)
    with gateway[0]() as db:
        result = admit_operation(
            db,
            token=issued.token,
            request=request_for(task, request_id="req_scoped" if other_owner else "req_task_two"),
            catalog=catalog,
            now=NOW,
        )
    assert result.decision == "DENY" and len(operations(gateway)) == 2
    with gateway[0]() as db, pytest.raises(OperationError, match="NOT_FOUND"):
        get_operation_status(
            db,
            token=issued.token,
            request_id="req_task_two" if other_owner else "req_scoped",
            now=NOW,
        )


def test_request_id_cannot_be_rebound_to_same_owners_other_task(gateway):
    admit(gateway)
    task, issued, catalog = new_binding(gateway)
    with gateway[0]() as db, pytest.raises(OperationError, match="IDEMPOTENCY_CONFLICT"):
        admit_operation(db, token=issued.token, request=request_for(task), catalog=catalog, now=NOW)


def test_concurrent_duplicates_reserve_once(gateway):
    grant(gateway)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: admit(gateway), range(8)))
    assert len({result.audit_event_ref for result in responses}) == 1
    assert len(operations(gateway)) == 1
    with gateway[0]() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_concurrent_conflicts_do_not_replace_winner(gateway):
    def submit(resource):
        try:
            return admit(gateway, arguments={"resource_id": resource})
        except OperationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(submit, [PIN.resource_id, "resource_other"]))
    assert result.count("IDEMPOTENCY_CONFLICT") == 1
    assert sum(isinstance(item, ToolResponse) for item in result) == 1
    assert len(operations(gateway)) == 1


def test_rollback_removes_reservation_and_audit(gateway, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OperationalError("PRIVATE_SQL", {}, Exception("PRIVATE_DATA"))

    monkeypatch.setattr("app.services.operation_ledger.record_decision", unavailable)
    with pytest.raises(AgentIdentityError, match="GATEWAY_UNAVAILABLE"):
        admit(gateway)
    assert operations(gateway) == []
    with gateway[0]() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_database_failure_is_sanitized(gateway, monkeypatch):
    with gateway[0]() as db:

        def unavailable(*args, **kwargs):
            raise OperationalError(
                "PRIVATE_SQL",
                {"token": gateway[2].token.get_secret_value()},
                Exception("PRIVATE_DATA"),
            )

        monkeypatch.setattr(db, "scalar", unavailable)
        with pytest.raises(AgentIdentityError) as error:
            admit_operation(db, token=gateway[2].token, request=request_for(gateway[1]), now=NOW)
    assert error.value.code == "GATEWAY_UNAVAILABLE" and "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("collision", ["exact", "conflict", "unresolved"])
def test_unique_violation_reload_compares_existing_identity(gateway, monkeypatch, collision):
    import app.services.operation_ledger as ledger

    admit(gateway)
    original = ledger._candidates
    calls = []

    def missed_then_reloaded(*args, **kwargs):
        calls.append(1)
        return [] if len(calls) == 1 or collision == "unresolved" else original(*args, **kwargs)

    monkeypatch.setattr(ledger, "_candidates", missed_then_reloaded)
    if collision == "exact":
        assert admit(gateway).decision == "DENY"
    else:
        with pytest.raises(OperationError) as error:
            admit(gateway, **({"purpose": "answer_question"} if collision == "conflict" else {}))
        assert error.value.code == (
            "IDEMPOTENCY_CONFLICT" if collision == "conflict" else "GATEWAY_UNAVAILABLE"
        )
    assert len(calls) == 2 and len(operations(gateway)) == 1


@pytest.mark.parametrize("revoked", [False, True])
def test_current_credential_required_on_every_replay(gateway, revoked):
    admit(gateway)
    factory, task, issued, _ = gateway
    if revoked:
        with factory() as db:
            revoke_agent_credential(
                db,
                owner=OWNER,
                task_ref=task.task_ref,
                credential_ref=issued.credential_ref,
                now=NOW,
            )
    with pytest.raises(AgentIdentityError, match="AUTH_INVALID"):
        admit(gateway, now=NOW if revoked else task.expires_at)
    assert len(operations(gateway)) == 1


@pytest.mark.parametrize("revoked", [False, True])
def test_old_admission_cannot_bypass_consent_changes(gateway, revoked):
    consent = grant(gateway)
    original = admit(gateway)
    if revoked:
        with gateway[0]() as db:
            revoke_scoped_consent(
                db,
                owner=OWNER,
                task_ref=gateway[1].task_ref,
                consent_ref=consent.consent_ref,
                now=NOW,
            )
    result = admit(gateway, now=NOW if revoked else consent.expires_at)
    assert result.decision == "DENY"
    assert result.reason_code == ("CONSENT_REVOKED" if revoked else "CONSENT_EXPIRED")
    assert result.audit_event_ref != original.audit_event_ref
    assert operations(gateway)[0].revision == 1
    assert admit(gateway).audit_event_ref == result.audit_event_ref


def test_denied_operation_does_not_reactivate_after_grant(gateway):
    first = admit(gateway)
    grant(gateway)
    assert admit(gateway) == first


def test_authorization_version_refresh_and_future_recheck(gateway):
    grant(gateway)
    admit(gateway)
    factory, task, issued, _ = gateway
    grant(gateway, action="tasks.list", resource_ids=[])
    with factory() as db:
        context = validate_agent_credential(db, token=issued.token, task_ref=task.task_ref, now=NOW)
    with factory() as db:
        current = db.get(GatewayTask, task.task_ref)
        op = db.scalar(select(GatewayOperation))
        consents = list(db.scalars(select(ScopedConsent)))
        with pytest.raises(OperationError, match="NOT_RESUMABLE"):
            validate_future_dispatch(
                context, request_for(task), current, consents, op, catalog=CATALOG, now=NOW
            )
    admit(gateway)
    with factory() as db:
        current = db.get(GatewayTask, task.task_ref)
        op = db.scalar(select(GatewayOperation))
        result = validate_future_dispatch(
            context,
            request_for(task),
            current,
            list(db.scalars(select(ScopedConsent))),
            op,
            catalog=CATALOG,
            now=NOW,
        )
        assert result.decision == "ALLOW" and op.authorization_version == 2 and op.revision == 1
        assert op.operation_status == "ADMITTED" and op.execution_started_at is None


def simulate_uncertainty(gateway, final="UNKNOWN"):
    """Offline state-machine fixture only; this does not invoke a trusted executor."""
    grant(gateway)
    admit(gateway)
    with gateway[0]() as db, db.begin():
        op = db.scalar(select(GatewayOperation))
        task = db.get(GatewayTask, op.task_ref)
        validate_transition(
            op.operation_status,
            "DISPATCHING",
            authorization=Authorization(decision="ALLOW", reason_code="EXECUTION_NOT_STARTED"),
            versions_match=True,
        )
        op.execution_started_at = NOW
        for state in ["DISPATCHING", "UNKNOWN"] if final == "UNKNOWN" else ["DISPATCHING"]:
            op.operation_status = state
            op.reason_code = "EXECUTION_UNCONFIRMED"
            op.revision += 1
            ref = record_decision(
                db,
                task,
                request_for(task),
                Authorization(decision="ALLOW", reason_code="EXECUTION_UNCONFIRMED"),
                NOW,
                operation=op,
            )
            op.audit_event_id = int(ref.removeprefix("event_"))


def test_unknown_replays_without_new_operation_or_attempt(gateway, member_b_contract):
    simulate_uncertainty(gateway)
    result = admit(gateway)
    assert result.execution_status == "UNKNOWN" and result.reason_code == "EXECUTION_UNCONFIRMED"
    assert (
        member_b_contract.ToolResponse.model_validate_json(
            result.model_dump_json()
        ).execution_status.value
        == "UNKNOWN"
    )
    assert admit(gateway) == result and len(operations(gateway)) == 1
    assert status(gateway).operation_state == "UNKNOWN"
    with pytest.raises(OperationError, match="IDEMPOTENCY_CONFLICT"):
        admit(gateway, request_id="req_alias")
    assert operations(gateway)[0].execution_finished_at is None


def test_dispatching_and_incomplete_history_fail_closed(gateway):
    simulate_uncertainty(gateway, final="DISPATCHING")
    with pytest.raises(OperationError) as error:
        admit(gateway)
    assert error.value.code == "OPERATION_IN_PROGRESS" and error.value.execution_uncertain
    assert status(gateway).execution_status == "UNKNOWN"


def test_unknown_requires_recorded_dispatch_history(gateway):
    simulate_uncertainty(gateway)
    with gateway[0]() as db, db.begin():
        op = db.scalar(select(GatewayOperation))
        history = list(db.scalars(select(AuditEvent).order_by(AuditEvent.id)))
        db.delete(history[1])
        op.revision = 1
        history[-1].detail = {**history[-1].detail, "revision": 1}
    with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
        admit(gateway)
    assert len(operations(gateway)) == 1


@pytest.mark.parametrize(
    "corruption", ["missing_audit", "revision_gap", "wrong_owner", "wrong_reason"]
)
def test_corrupt_operation_history_is_not_a_new_operation(gateway, corruption):
    admit(gateway)
    with gateway[0]() as db, db.begin():
        op = db.scalar(select(GatewayOperation))
        audit = db.get(AuditEvent, op.audit_event_id)
        if corruption == "missing_audit":
            op.audit_event_id = None
        elif corruption == "revision_gap":
            op.revision = 5
        elif corruption == "wrong_owner":
            audit.user_id = "foreign-owner"
        else:
            op.reason_code = "EXECUTION_NOT_STARTED"
    with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
        admit(gateway)
    assert len(operations(gateway)) == 1


@pytest.mark.parametrize(
    "current,target",
    [
        ("UNKNOWN", "DISPATCHING"),
        ("DENIED", "ADMITTED"),
        ("SUCCEEDED", "DISPATCHING"),
        ("ADMITTED", "SUCCEEDED"),
        ("garbage", "ADMITTED"),
    ],
)
def test_invalid_future_state_transition(current, target):
    with pytest.raises(OperationError, match="NOT_RESUMABLE"):
        validate_transition(current, target)


def test_future_dispatch_requires_authorization_and_current_version():
    for authorization, versions in [
        (None, True),
        (Authorization(decision="DENY", reason_code="CONSENT_REVOKED"), True),
        (Authorization(decision="ALLOW", reason_code="EXECUTION_NOT_STARTED"), False),
    ]:
        with pytest.raises(OperationError, match="NOT_RESUMABLE"):
            validate_transition(
                "ADMITTED", "DISPATCHING", authorization=authorization, versions_match=versions
            )


def test_canonical_hash_excludes_transport_identity_and_preserves_payload_bytes(gateway):
    task = gateway[1]
    first = request_for(
        task,
        action="email.send",
        arguments={
            "recipient": "safe@EXAMPLE.TEST",
            "subject": " S ",
            "body": "B\r\n",
            "attachment_resource_ids": ["r1", "r2"],
        },
    )
    second = request_for(
        task,
        action="email.send",
        arguments={
            "recipient": "safe@example.test",
            "subject": " S ",
            "body": "B\r\n",
            "attachment_resource_ids": ["r1", "r2"],
        },
        request_id="req_other",
        idempotency_key="key_other",
    )
    assert request_digests(OWNER.owner_id, first, SCOPE) == request_digests(
        OWNER.owner_id, second, SCOPE
    )
    changed = request_for(
        task,
        action="email.send",
        arguments={
            "recipient": "safe@example.test",
            "subject": " S ",
            "body": "B\n",
            "attachment_resource_ids": ["r1", "r2"],
        },
    )
    assert request_digests(OWNER.owner_id, first, SCOPE) != request_digests(
        OWNER.owner_id, changed, SCOPE
    )


def test_no_private_payload_or_credential_in_ledger_or_audit(gateway):
    marker = "SYNTHETIC_PRIVATE_CONTENT_NOT_TO_PERSIST"
    admit(
        gateway,
        action="email.send",
        arguments={"recipient": "safe@example.test", "subject": marker, "body": marker},
    )
    with gateway[0]() as db:
        rows = repr(db.execute(text("SELECT * FROM gateway_operations")).all()) + repr(
            db.execute(text("SELECT * FROM audit_events")).all()
        )
    assert marker not in rows and gateway[2].token.get_secret_value() not in rows


def test_status_is_authenticated_metadata_only(gateway):
    admit(gateway)
    _, _, issued, client = gateway
    path = "/api/gateway/v1/operations/req_scoped"
    assert client.get(path).status_code == 401
    result = client.get(
        path, headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"}
    )
    assert result.status_code == 200 and result.json()["operation_ref"].startswith("op_")
    assert (
        not {"arguments", "idempotency_key", "canonical_request_digest", "owner_id"}
        & result.json().keys()
    )
    assert (
        client.get(
            "/api/gateway/v1/operations/unknown",
            headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"},
        ).status_code
        == 404
    )


@pytest.mark.parametrize("uncertain", [False, True])
def test_sqlite_restart_reuses_persisted_operation(gateway, uncertain):
    if uncertain:
        simulate_uncertainty(gateway)
    else:
        grant(gateway)
    first = admit(gateway)
    old = gateway[0].kw["bind"]
    url = old.url
    old.dispose()
    engine = create_engine(url, hide_parameters=True)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        with factory() as db:
            second = admit_operation(
                db,
                token=gateway[2].token,
                request=request_for(gateway[1]),
                catalog=CATALOG,
                now=NOW,
            )
        assert first == second
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(GatewayOperation)) == 1
    finally:
        engine.dispose()


def test_db_constraints_and_capacity(gateway):
    admit(gateway)
    with gateway[0]() as db, pytest.raises(IntegrityError):
        with db.begin():
            db.scalar(select(GatewayOperation)).operation_status = "DISPATCHING"
    for i in range(1, 20):
        admit(
            gateway,
            request_id=f"req_{i}",
            idempotency_key=f"key_{i}",
            purpose=f"synthetic-purpose-{i}",
        )
    with pytest.raises(OperationError, match="CAPACITY_EXCEEDED"):
        admit(
            gateway, request_id="req_over", idempotency_key="key_over", purpose="synthetic-overflow"
        )
    assert admit(gateway).decision == "DENY" and len(operations(gateway)) == 20


def test_migration_structure_and_mysql_ddl_without_applying():
    path = Path(__file__).parents[1] / "migrations/versions/0004_operation_ledger.py"
    tree = ast.parse(path.read_text())
    values = {
        n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
    }
    assert (
        values["down_revision"] == "0003_scoped_consent"
        and values["revision"] == "0004_operation_ledger"
    )
    ddl = str(CreateTable(GatewayOperation.__table__).compile(dialect=mysql.dialect()))
    assert all(
        name in ddl
        for name in [
            "uq_operation_owner_request",
            "uq_operation_task_key",
            "uq_operation_task_digest",
            "DATETIME(6)",
            "ascii_bin",
            "InnoDB",
        ]
    )


@pytest.mark.parametrize("allowed", [False, True])
def test_http_ledger_has_no_tool_filesystem_smtp_or_process_effects(gateway, monkeypatch, allowed):
    import builtins
    import smtplib
    import subprocess

    if allowed:
        grant(gateway)

    def forbidden(*args, **kwargs):
        raise AssertionError("External effect during operation admission")

    factory, task, issued, client = gateway
    with monkeypatch.context() as guards:
        guards.setattr(builtins, "open", forbidden)
        guards.setattr(Path, "open", forbidden)
        guards.setattr(smtplib, "SMTP", forbidden)
        guards.setattr(smtplib, "SMTP_SSL", forbidden)
        guards.setattr(subprocess, "Popen", forbidden)
        response = client.post(
            "/api/gateway/v1/execute",
            json=request_for(task).model_dump(mode="json"),
            headers={"Authorization": f"Bearer {issued.token.get_secret_value()}"},
        )
    assert response.status_code == 200 and response.json()["decision"] == (
        "ALLOW" if allowed else "DENY"
    )
    assert response.json()["execution_status"] == "NOT_EXECUTED"


def test_unique_reload_rechecks_current_consent(gateway, monkeypatch):
    import app.services.operation_ledger as ledger

    consent = grant(gateway)
    admit(gateway)
    with gateway[0]() as db:
        revoke_scoped_consent(
            db, owner=OWNER, task_ref=gateway[1].task_ref, consent_ref=consent.consent_ref, now=NOW
        )
    original = ledger._candidates
    calls = []

    def reload(*args, **kwargs):
        calls.append(1)
        return [] if len(calls) == 1 else original(*args, **kwargs)

    monkeypatch.setattr(ledger, "_candidates", reload)
    assert admit(gateway).reason_code == "CONSENT_REVOKED"
    assert len(operations(gateway)) == 1


def test_unknown_history_is_not_execution_authority_after_revocation(gateway):
    simulate_uncertainty(gateway)
    factory, task, issued, _ = gateway
    with factory() as db:
        consent = db.scalar(select(ScopedConsent))
    with factory() as db:
        revoke_scoped_consent(
            db, owner=OWNER, task_ref=task.task_ref, consent_ref=consent.consent_ref, now=NOW
        )
    assert admit(gateway).execution_status == "UNKNOWN"
    with factory() as db:
        context = validate_agent_credential(db, token=issued.token, task_ref=task.task_ref, now=NOW)
    with factory() as db:
        result = validate_future_dispatch(
            context,
            request_for(task),
            db.get(GatewayTask, task.task_ref),
            list(db.scalars(select(ScopedConsent))),
            db.scalar(select(GatewayOperation)),
            catalog=CATALOG,
            now=NOW,
        )
    assert result.decision == "DENY" and result.reason_code == "CONSENT_REVOKED"


@pytest.mark.parametrize("kind", ["consent", "credential"])
def test_sqlite_ledger_revocation_race(gateway, monkeypatch, kind):
    from concurrent.futures import TimeoutError
    from threading import Event

    import app.services.agent_identity as identity
    import app.services.scoped_consent as policy

    consent = grant(gateway)
    factory, task, issued, _ = gateway
    module = policy if kind == "consent" else identity
    original = module._owned_task
    locked, started, release = Event(), Event(), Event()

    def hold(*args, **kwargs):
        result = original(*args, **kwargs)
        locked.set()
        if not release.wait(5):
            raise RuntimeError("Test lock release timed out")
        return result

    monkeypatch.setattr(module, "_owned_task", hold)

    def revoke():
        with factory() as db:
            if kind == "consent":
                revoke_scoped_consent(
                    db,
                    owner=OWNER,
                    task_ref=task.task_ref,
                    consent_ref=consent.consent_ref,
                    now=NOW,
                )
            else:
                revoke_agent_credential(
                    db,
                    owner=OWNER,
                    task_ref=task.task_ref,
                    credential_ref=issued.credential_ref,
                    now=NOW,
                )

    def read():
        started.set()
        try:
            return admit(gateway).reason_code
        except AgentIdentityError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(revoke)
        assert locked.wait(5)
        reader = pool.submit(read)
        try:
            assert started.wait(5)
            with pytest.raises(TimeoutError):
                reader.result(0.1)
        finally:
            release.set()
        writer.result(5)
        assert reader.result(5) == ("CONSENT_REVOKED" if kind == "consent" else "AUTH_INVALID")
    assert len(operations(gateway)) == (1 if kind == "consent" else 0)


@pytest.mark.parametrize("level,accepted", [("READ COMMITTED", True), ("REPEATABLE READ", False)])
def test_mysql_isolation_requirement_without_connection(level, accepted):
    from types import SimpleNamespace

    from app.services.operation_ledger import _isolation

    db = SimpleNamespace(
        connection=lambda: SimpleNamespace(
            dialect=SimpleNamespace(name="mysql"),
            get_isolation_level=lambda: level,
        )
    )
    if accepted:
        _isolation(db)
    else:
        with pytest.raises(OperationError, match="GATEWAY_UNAVAILABLE"):
            _isolation(db)
