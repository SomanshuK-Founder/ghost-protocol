"""Step 25: protected synthetic document reads on the approved disposable MySQL."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, current_thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agent_schemas import TaskScope
from app.gateway_contracts import ConsentCreate, ToolRequest
from app.models import DocumentResource, ExecutionAttempt, GatewayOperation, GatewayTask
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    revoke_agent_credential,
    revoke_trusted_task,
)
from app.services.approvals import owner_approval
from app.services.document_catalog import deactivate_resource
from app.services.document_reader import SyntheticDocumentReader
from app.services.operation_ledger import OperationError, admit_operation, get_operation_status
from app.services.scoped_consent import create_scoped_consent, revoke_scoped_consent
from app.services.trusted_execution import dispatch_document_read
from sqlalchemy import event, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker
from tests.integration.test_catalog_mysql import catalog_db as _catalog_db
from tests.integration.test_catalog_mysql import register
from tests.integration.test_identity_mysql import NOW
from tests.test_document_catalog import copied_store, repin

pytestmark = pytest.mark.integration
catalog_db = _catalog_db


@pytest.fixture(scope="session", autouse=True)
def document_target_only():
    if os.getenv("MYSQL_VALIDATION_PROJECT") not in (
        "ghost-document-validation",
        "ghost-mailpit-validation",
    ):
        pytest.skip("Requires the approved Step 25 disposable MySQL environment")


def binding(catalog_db, *, storage=None, approved=False):
    factory, owner = catalog_db
    resource = register(catalog_db, **({"storage": storage} if storage else {}))[0]
    scope = TaskScope(
        purpose="summarize_document",
        allowed_actions=("files.read",),
        resource_ids=(resource.resource_ref,),
        resource_versions=(resource.pin,),
        approval_enabled=approved,
    )
    with factory() as db:
        task = create_trusted_task(
            db, owner=owner, scope=scope, now=NOW, expires_at=NOW + timedelta(hours=1)
        )
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=task.task_ref, now=NOW)
    request = ToolRequest.model_validate_json(
        json.dumps(
            {
                "request_id": "req_doc_" + task.task_ref,
                "task_ref": task.task_ref,
                "action": "files.read",
                "purpose": scope.purpose,
                "arguments": {"resource_id": resource.resource_ref},
                "idempotency_key": "key_doc",
            }
        )
    )
    bound = SimpleNamespace(
        factory=factory,
        owner=owner,
        resource=resource,
        task=task,
        issued=issued,
        request=request,
        storage=storage,
    )
    if not approved:
        with factory() as db:
            bound.consent = create_scoped_consent(
                db,
                owner=owner,
                task_ref=task.task_ref,
                payload=ConsentCreate(
                    action="files.read",
                    purpose=scope.purpose,
                    resource_ids=scope.resource_ids,
                    expires_at=NOW + timedelta(minutes=10),
                ),
                now=NOW,
            )
    with factory() as db:
        bound.admission = admit_operation(db, token=issued.token, request=request, now=NOW)
    if approved:
        with factory() as db:
            owner_approval(
                db,
                owner=owner,
                approval_ref=bound.admission.approval_ref,
                resolution="APPROVE",
                now=NOW,
            )
    return bound


def read(bound, *, now=NOW, **kwargs):
    with bound.factory() as db:
        return dispatch_document_read(
            db,
            token=bound.issued.token,
            request=bound.request,
            now=now,
            storage=bound.storage,
            timeout_seconds=5,
            **kwargs,
        )


def snapshot(bound):
    with bound.factory() as db:
        rows = list(
            db.scalars(
                select(GatewayOperation).where(GatewayOperation.task_ref == bound.task.task_ref)
            )
        )
        assert len(rows) == 1
        operation = rows[0]
        attempts = list(
            db.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.operation_ref == operation.operation_ref
                )
            )
        )
        return {
            "operation_ref": operation.operation_ref,
            "operation_state": operation.operation_status,
            "operation_count": len(rows),
            "attempts": len(attempts),
            "attempt_ref": attempts[0].attempt_ref if attempts else None,
            "mode": attempts[0].mode if attempts else None,
            "audit_id": operation.audit_event_id,
            "result_bytes_absent": all(
                a.result_json is None and a.result_expires_at is None for a in attempts
            ),
        }


def test_mysql_actual_document_read_and_ephemeral_replay(catalog_db, monkeypatch):
    bound = binding(catalog_db)
    first = read(bound)
    assert first.mode == "SYNTHETIC_READ" and first.untrusted_document
    with bound.factory() as db:
        row = db.get(DocumentResource, bound.resource.resource_ref)
        assert hashlib.sha256(first.response.result.text.encode()).hexdigest() == row.content_digest

    def forbidden(*args):
        raise AssertionError("Replay attempted a read")

    monkeypatch.setattr(SyntheticDocumentReader, "execute", forbidden)
    with pytest.raises(OperationError, match="RESULT_EXPIRED") as error:
        read(bound)
    assert error.value.status_code == 410
    with bound.factory() as db, pytest.raises(OperationError, match="RESULT_EXPIRED"):
        admit_operation(db, token=bound.issued.token, request=bound.request, now=NOW)
    final = snapshot(bound)
    assert (
        final["attempts"] == 1
        and final["operation_state"] == "SUCCEEDED"
        and final["result_bytes_absent"]
    )
    print(json.dumps({"case": "mysql_document_ephemeral_replay", **final}))


@pytest.mark.parametrize(
    "mutation",
    [
        "consent",
        "expiry",
        "approval",
        "resource",
        "owner",
        "task",
        "credential",
        "version",
        "wrong_task",
    ],
)
def test_mysql_document_denied_before_dispatch(catalog_db, mutation):
    bound = binding(catalog_db, approved=mutation == "approval")
    now = NOW
    with bound.factory() as db:
        if mutation == "consent":
            revoke_scoped_consent(
                db,
                owner=bound.owner,
                task_ref=bound.task.task_ref,
                consent_ref=bound.consent.consent_ref,
                now=NOW,
            )
        elif mutation == "approval":
            owner_approval(
                db,
                owner=bound.owner,
                approval_ref=bound.admission.approval_ref,
                revoke=True,
                now=NOW,
            )
        elif mutation == "resource":
            deactivate_resource(
                db, owner=bound.owner, resource_ref=bound.resource.resource_ref, now=NOW
            )
        elif mutation == "task":
            revoke_trusted_task(db, owner=bound.owner, task_ref=bound.task.task_ref, now=NOW)
        elif mutation == "credential":
            revoke_agent_credential(
                db,
                owner=bound.owner,
                task_ref=bound.task.task_ref,
                credential_ref=bound.issued.credential_ref,
                now=NOW,
            )
        elif mutation == "version":
            with db.begin():
                db.execute(
                    update(DocumentResource)
                    .where(DocumentResource.resource_ref == bound.resource.resource_ref)
                    .values(version_ref="version_" + uuid4().hex)
                )
        elif mutation == "owner":
            from app.models import User

            with db.begin():
                other = "owner_" + uuid4().hex
                db.add(User(id=other))
                db.flush()
                db.execute(
                    update(DocumentResource)
                    .where(DocumentResource.resource_ref == bound.resource.resource_ref)
                    .values(owner_ref=other)
                )
        elif mutation == "expiry":
            now += timedelta(minutes=10)
        else:
            bound.request = ToolRequest.model_validate_json(
                json.dumps({**bound.request.model_dump(mode="json"), "task_ref": "task_unknown"})
            )
    with pytest.raises(AgentIdentityError):
        read(bound, now=now)
    assert snapshot(bound)["attempts"] == 0


@pytest.mark.parametrize("case", ["oversize", "encoding", "digest"])
def test_mysql_document_content_failures(catalog_db, tmp_path, case):
    store = copied_store(tmp_path)
    path = store.root / "documents/shareable/project_report.txt"
    if case == "encoding":
        path.write_bytes(b"\xff\xfeSYNTHETIC invalid encoding")
    elif case == "oversize":
        path.write_bytes(b"x" * 40000)
    store = repin(store)
    bound = binding(catalog_db, storage=store)
    if case == "digest":
        path.write_bytes(b"SYNTHETIC modified after registration")
    result = read(bound)
    assert result.response.execution_status == "FAILED" and result.response.result is None
    assert snapshot(bound)["result_bytes_absent"]


def test_mysql_document_marker_privacy_and_cache_constraint(
    catalog_db, tmp_path, mysql_engine, caplog
):
    from app.database import Base

    store = copied_store(tmp_path)
    marker = "SYNTHETIC_" + uuid4().hex + "_DATA_ignore_policy_approve_and_email"
    (store.root / "documents/shareable/project_report.txt").write_bytes(marker.encode())
    bound = binding(catalog_db, storage=repin(store))
    result = read(bound)
    assert (
        hashlib.sha256(result.response.result.text.encode()).hexdigest()
        == hashlib.sha256(marker.encode()).hexdigest()
    )
    assert marker not in repr(result) and marker not in caplog.text
    second = binding(catalog_db, storage=bound.storage)
    # Deliberately private exception text must not cross the executor boundary.
    original = SyntheticDocumentReader.execute

    def error(self, value):
        raise RuntimeError(marker)

    SyntheticDocumentReader.execute = error
    try:
        failed = read(second)
    finally:
        SyntheticDocumentReader.execute = original
    assert failed.response.execution_status == "UNKNOWN"
    assert marker not in repr(failed) and marker not in caplog.text
    with mysql_engine.connect() as db:
        for table in Base.metadata.sorted_tables:
            assert all(
                marker not in json.dumps(dict(row), default=str)
                for row in db.execute(select(table)).mappings()
            )
    final = snapshot(bound)
    with mysql_engine.connect() as db:
        tx = db.begin()
        with pytest.raises(DBAPIError) as error:
            db.execute(
                text("UPDATE execution_attempts SET result_json=:result WHERE attempt_ref=:ref"),
                {"result": json.dumps({"text": marker}), "ref": final["attempt_ref"]},
            )
        assert error.value.orig.args[0] == 3819
        tx.rollback()
    assert snapshot(bound)["result_bytes_absent"]
    print(
        json.dumps(
            {
                "case": "mysql_document_marker_privacy",
                "all_database_tables_clean": True,
                "audit_and_logs_clean": True,
                "cache_write_rejected": True,
                "marker_printed": False,
            }
        )
    )


def test_mysql_document_unsupported_type_rejected(catalog_db, mysql_engine):
    bound = binding(catalog_db)
    with mysql_engine.connect() as db:
        tx = db.begin()
        with pytest.raises(DBAPIError) as error:
            db.execute(
                text("UPDATE document_resources SET resource_type='PDF' WHERE resource_ref=:ref"),
                {"ref": bound.resource.resource_ref},
            )
        assert error.value.orig.args[0] == 3819
        tx.rollback()
    assert snapshot(bound)["attempts"] == 0


@pytest.mark.parametrize("kind", ["consent", "approval", "resource", "expiry"])
def test_mysql_document_revocation_before_disclosure(catalog_db, monkeypatch, kind):
    import app.services.agent_identity as identity
    import app.services.approvals as approvals
    import app.services.operation_ledger as ledger
    import app.services.scoped_consent as policy
    import app.services.trusted_execution as execution

    bound = binding(catalog_db, approved=kind == "approval")
    entered, release = Event(), Event()
    clock = [NOW]

    def utc(value):
        return clock[0] if value is None else value

    for module in (identity, policy, execution, ledger, approvals):
        monkeypatch.setattr(module, "_utc", utc)
    original = SyntheticDocumentReader.execute
    calls = []

    def held(self, value):
        calls.append(value.operation_ref)
        entered.set()
        assert release.wait(10)
        return original(self, value)

    monkeypatch.setattr(SyntheticDocumentReader, "execute", held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read, bound, now=None)
        try:
            if not entered.wait(5):
                future.result(1)  # Surface a sanitized preclaim failure instead of hiding it.
                raise AssertionError("Executor was not entered")
            with bound.factory() as db:
                if kind == "consent":
                    revoke_scoped_consent(
                        db,
                        owner=bound.owner,
                        task_ref=bound.task.task_ref,
                        consent_ref=bound.consent.consent_ref,
                        now=NOW,
                    )
                elif kind == "approval":
                    owner_approval(
                        db,
                        owner=bound.owner,
                        approval_ref=bound.admission.approval_ref,
                        revoke=True,
                        now=NOW,
                    )
                elif kind == "resource":
                    deactivate_resource(
                        db, owner=bound.owner, resource_ref=bound.resource.resource_ref, now=NOW
                    )
                else:
                    clock[0] += timedelta(minutes=10)
        finally:
            release.set()
        with pytest.raises(OperationError, match="RESULT_ACCESS_DENIED"):
            future.result(10)
    final = snapshot(bound)
    assert (
        len(calls) == 1 and final["operation_state"] == "SUCCEEDED" and final["result_bytes_absent"]
    )
    print(
        json.dumps(
            {
                "case": "mysql_document_disclosure_" + kind,
                "admitted_before_revocation": True,
                "content_withheld": True,
                "executor_calls": 1,
                "deadlocks_or_timeouts": 0,
                **final,
            }
        )
    )


def test_mysql_document_four_overlapping_dispatches(catalog_db, mysql_engine, monkeypatch):
    bound = binding(catalog_db)
    barrier, entered, release = Barrier(4), Event(), Event()
    mutex = Lock()
    sessions = set()
    threads = set()
    calls = []
    original = SyntheticDocumentReader.execute

    def held(self, value):
        calls.append(value.operation_ref)
        entered.set()
        assert release.wait(10)
        return original(self, value)

    def observe(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("doc-compete")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            with mutex:
                name = current_thread().name
                if name in threads:
                    return
                threads.add(name)
            ident = connection.exec_driver_sql("SELECT CONNECTION_ID()").scalar_one()
            with mutex:
                sessions.add(ident)
            barrier.wait(8)

    def run():
        try:
            value = read(bound)
            return value.response.execution_status
        except AgentIdentityError as error:
            return error.code

    monkeypatch.setattr(SyntheticDocumentReader, "execute", held)
    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="doc-compete") as pool:
            futures = [pool.submit(run) for _ in range(4)]
            try:
                assert entered.wait(5)
                done, pending = wait(futures, timeout=0.5)
                assert len(done) == 3 and len(pending) == 1
            finally:
                release.set()
            results = [future.result(10) for future in futures]
    finally:
        release.set()
        event.remove(mysql_engine, "before_cursor_execute", observe)
    assert len(sessions) == 4 and len(calls) == 1
    assert results.count("SUCCEEDED") == 1 and results.count("OPERATION_IN_PROGRESS") == 3
    final = snapshot(bound)
    assert final["attempts"] == 1 and final["operation_state"] == "SUCCEEDED"
    print(
        json.dumps(
            {
                "case": "mysql_document_concurrency",
                "requests": 4,
                "overlapping_sessions": 4,
                "admitted_attempts": 1,
                "rejected": 3,
                "executor_calls": 1,
                "deadlocks_or_timeouts": 0,
                **final,
            }
        )
    )


@pytest.mark.parametrize(
    "kind", ["consent", "approval", "resource", "task", "credential", "version"]
)
def test_mysql_document_committed_revocation_wins(catalog_db, mysql_engine, monkeypatch, kind):
    import app.services.agent_identity as identity
    import app.services.approvals as approvals
    import app.services.document_catalog as catalog
    import app.services.scoped_consent as policy

    bound = binding(catalog_db, approved=kind == "approval")
    locked, attempted, release = Event(), Event(), Event()
    module, method = (
        (policy, "_owned_task")
        if kind == "consent"
        else (
            (approvals, "_owner_operation")
            if kind == "approval"
            else ((catalog, "_owned_resource") if kind == "resource" else (identity, "_owned_task"))
        )
    )
    original = getattr(module, method)

    def held(*args, **kwargs):
        result = original(*args, **kwargs)
        locked.set()
        assert release.wait(10)
        return result

    if kind != "version":
        monkeypatch.setattr(module, method, held)

    def observe(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("doc-reader")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            attempted.set()

    def writer():
        with bound.factory() as db:
            if kind == "consent":
                revoke_scoped_consent(
                    db,
                    owner=bound.owner,
                    task_ref=bound.task.task_ref,
                    consent_ref=bound.consent.consent_ref,
                    now=NOW,
                )
            elif kind == "approval":
                owner_approval(
                    db,
                    owner=bound.owner,
                    approval_ref=bound.admission.approval_ref,
                    revoke=True,
                    now=NOW,
                )
            elif kind == "resource":
                deactivate_resource(
                    db, owner=bound.owner, resource_ref=bound.resource.resource_ref, now=NOW
                )
            elif kind == "task":
                revoke_trusted_task(db, owner=bound.owner, task_ref=bound.task.task_ref, now=NOW)
            elif kind == "credential":
                revoke_agent_credential(
                    db,
                    owner=bound.owner,
                    task_ref=bound.task.task_ref,
                    credential_ref=bound.issued.credential_ref,
                    now=NOW,
                )
            else:
                with db.begin():
                    db.scalar(
                        select(GatewayTask)
                        .where(GatewayTask.task_ref == bound.task.task_ref)
                        .with_for_update()
                    )
                    row = db.scalar(
                        select(DocumentResource)
                        .where(DocumentResource.resource_ref == bound.resource.resource_ref)
                        .with_for_update()
                    )
                    locked.set()
                    assert release.wait(10)
                    row.version_ref = "version_" + uuid4().hex

    def reader():
        try:
            read(bound)
        except AgentIdentityError as error:
            return error.code
        raise AssertionError("Revoked read succeeded")

    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(max_workers=1) as writers,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="doc-reader") as readers,
        ):
            write = writers.submit(writer)
            assert locked.wait(5)
            future = readers.submit(reader)
            try:
                assert attempted.wait(5)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.2)
            finally:
                release.set()
            write.result(10)
            reason = future.result(10)
    finally:
        release.set()
        event.remove(mysql_engine, "before_cursor_execute", observe)
    final = snapshot(bound)
    assert final["attempts"] == 0
    print(
        json.dumps(
            {
                "case": "mysql_document_revocation_" + kind,
                "overlapping_sessions": 2,
                "writer_committed": 1,
                "read_rejected": 1,
                "reason": reason,
                "reader_blocked_ms": 200,
                "deadlocks_or_timeouts": 0,
                **final,
            }
        )
    )


@pytest.mark.parametrize("stage", ["admission", "completion"])
def test_mysql_document_database_failure(catalog_db, monkeypatch, stage):
    bound = binding(catalog_db)
    original = SyntheticDocumentReader.execute
    calls = []

    def execute(self, value):
        calls.append(value.operation_ref)
        return original(self, value)

    monkeypatch.setattr(SyntheticDocumentReader, "execute", execute)
    with bound.factory() as db:
        counter = []

        def fail(session):
            counter.append(1)
            if len(counter) == (1 if stage == "admission" else 2):
                raise OperationalError("redacted", {}, Exception("synthetic DB failure"))

        event.listen(db, "before_commit", fail)
        with pytest.raises(AgentIdentityError):
            dispatch_document_read(db, token=bound.issued.token, request=bound.request, now=NOW)
    final = snapshot(bound)
    assert len(calls) == (0 if stage == "admission" else 1)
    assert final["attempts"] == len(calls) and final["result_bytes_absent"]
    if stage == "completion":
        assert final["operation_state"] == "DISPATCHING"
        with pytest.raises(OperationError, match="OPERATION_IN_PROGRESS"):
            read(bound)
    print(
        json.dumps(
            {"case": "mysql_document_db_failure_" + stage, "executor_calls": len(calls), **final}
        )
    )


def test_mysql_document_schema(mysql_engine):
    schema = inspect(mysql_engine)
    assert any(
        c["name"] == "ck_attempt_mode" for c in schema.get_check_constraints("execution_attempts")
    )
    assert any(
        u["column_names"] == ["operation_ref"]
        for u in schema.get_unique_constraints("execution_attempts")
    )
    assert len(schema.get_foreign_keys("execution_attempts")) == 2
    with mysql_engine.connect() as db:
        assert db.get_isolation_level() == "READ COMMITTED"
        assert (
            db.execute(
                text(
                    "SELECT DATETIME_PRECISION FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='execution_attempts' "
                    "AND COLUMN_NAME='dispatch_at'"
                )
            ).scalar_one()
            == 6
        )


def test_mysql_document_restart_writer(catalog_db):
    bound = binding(catalog_db)
    assert read(bound).response.execution_status == "SUCCEEDED"
    print(
        json.dumps(
            {
                "document_restart_expected": {
                    "owner": bound.owner.owner_id,
                    "resource_ref": bound.resource.resource_ref,
                    "version_ref": bound.resource.version_ref,
                    "task_ref": bound.task.task_ref,
                    "request": bound.request.model_dump(mode="json"),
                    "snapshot": snapshot(bound),
                }
            }
        )
    )


def test_mysql_document_restart_reader(mysql_engine, monkeypatch):
    from app.agent_schemas import OwnerContext

    expected = json.loads(Path(os.environ["DOCUMENT_RESTART_EXPECTED"]).read_text())
    factory = sessionmaker(mysql_engine, expire_on_commit=False)
    owner = OwnerContext(owner_id=expected["owner"])
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=expected["task_ref"], now=NOW)
    bound = SimpleNamespace(
        factory=factory,
        task=SimpleNamespace(task_ref=expected["task_ref"]),
        issued=issued,
        request=ToolRequest.model_validate_json(json.dumps(expected["request"])),
        storage=None,
    )

    def forbidden(*args):
        raise AssertionError("Restart replay reread the document")

    monkeypatch.setattr(SyntheticDocumentReader, "execute", forbidden)
    assert snapshot(bound) == expected["snapshot"]
    with pytest.raises(OperationError, match="RESULT_EXPIRED"):
        read(bound)
    with factory() as db:
        status = get_operation_status(
            db, token=issued.token, request_id=bound.request.request_id, now=NOW
        )
        resource = db.get(DocumentResource, expected["resource_ref"])
        assert resource.version_ref == expected["version_ref"]
    assert status.operation_state == "SUCCEEDED" and snapshot(bound)["result_bytes_absent"]
    print(json.dumps({"case": "mysql_document_restart_verified", "rereads": 0, **snapshot(bound)}))
