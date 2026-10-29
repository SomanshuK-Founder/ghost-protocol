"""Step 22: synthetic catalog validation on the explicitly approved MySQL target."""

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, current_thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agent_schemas import OwnerContext, TaskScope
from app.gateway_contracts import ConsentCreate, ToolRequest
from app.models import (
    AuditEvent,
    DocumentResource,
    ExecutionAttempt,
    GatewayOperation,
    GatewayTask,
    User,
)
from app.services.agent_identity import (
    AgentIdentityError,
    create_trusted_task,
    issue_agent_credential,
    validate_agent_credential,
)
from app.services.document_catalog import (
    DEFAULT_STORAGE,
    FixtureRegistration,
    deactivate_resource,
    list_authorized_metadata,
    lookup_resource,
    register_synthetic_resources,
)
from app.services.operation_ledger import admit_operation
from app.services.scoped_consent import (
    authorize_request,
    create_scoped_consent,
    revoke_scoped_consent,
)
from sqlalchemy import event, func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import sessionmaker
from tests.integration.test_identity_mysql import NOW

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def require_catalog_target():
    if os.getenv("MYSQL_VALIDATION_PROJECT") not in (
        "ghost-catalog-validation",
        "ghost-document-validation",
        "ghost-mailpit-validation",
    ):
        pytest.skip("Requires the explicitly approved Step 22 disposable MySQL target")


@pytest.fixture
def catalog_db(mysql_engine):
    factory = sessionmaker(mysql_engine, expire_on_commit=False, autoflush=False)
    owner = OwnerContext(owner_id="catalog_" + uuid4().hex)
    with factory.begin() as db:
        db.add(User(id=owner.owner_id))
    return factory, owner


def register(binding, names=("doc_project_report",), **kwargs):
    factory, owner = binding
    with factory() as db:
        return register_synthetic_resources(
            db, owner=owner, selection=FixtureRegistration(fixtures=names), now=NOW, **kwargs
        )


def bind(binding, resources, *, consent=True):
    factory, owner = binding
    scope = TaskScope(
        purpose="summarize_document",
        allowed_actions=("files.list_authorized", "files.read"),
        resource_ids=tuple(r.resource_ref for r in resources),
        resource_versions=tuple(r.pin for r in resources),
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
                "request_id": "req_catalog_" + task.task_ref,
                "task_ref": task.task_ref,
                "action": "files.list_authorized",
                "purpose": scope.purpose,
                "arguments": {},
                "idempotency_key": "key_catalog",
            }
        )
    )
    bound = SimpleNamespace(factory=factory, owner=owner, task=task, issued=issued, request=request)
    if consent:
        with factory() as db:
            bound.consent = create_scoped_consent(
                db,
                owner=owner,
                task_ref=task.task_ref,
                now=NOW,
                payload=ConsentCreate(
                    action=request.action,
                    purpose=request.purpose,
                    resource_ids=scope.resource_ids,
                    expires_at=NOW + timedelta(minutes=10),
                ),
            )
    with factory() as db:
        bound.response = admit_operation(db, token=issued.token, request=request, now=NOW)
    return bound


def listing(bound, *, now=NOW):
    with bound.factory() as db:
        return list_authorized_metadata(
            db, token=bound.issued.token, request=bound.request, now=now
        )


def counts(binding):
    factory, owner = binding
    with factory() as db:
        return db.scalar(
            select(func.count())
            .select_from(DocumentResource)
            .where(DocumentResource.owner_ref == owner.owner_id)
        )


def safe_denial(call):
    try:
        call()
    except AgentIdentityError as error:
        return error.code
    raise AssertionError("Authorization unexpectedly succeeded")


def test_mysql_catalog_persistence_and_safe_listing(catalog_db):
    resources = register(catalog_db, ("doc_project_report", "doc_tax_2026"))
    assert register(catalog_db)[0] == resources[0]
    bound = bind(catalog_db, resources)
    assert bound.response.decision == "ALLOW" and bound.response.execution_status == "NOT_EXECUTED"
    result = listing(bound)
    assert {r.resource_id for r in result.resources} == {r.resource_ref for r in resources}
    assert all(set(r.model_dump()) == {"resource_id", "version_ref"} for r in result.resources)
    assert {r.classification for r in resources} == {"SHAREABLE", "PRIVATE_ORIGINAL"}
    with bound.factory() as db:
        for metadata in resources:
            row = db.get(DocumentResource, metadata.resource_ref)
            assert metadata.owner_ref == row.owner_ref == bound.owner.owner_id
            assert row.version_ref == metadata.version_ref
            assert row.created_at == row.updated_at == NOW and row.created_at.microsecond == 678901
            assert len(row.content_digest) == 64 and row.active
            assert row.storage_reference.startswith("ghost_demo_v1_")
        assert (
            db.scalar(
                select(func.count())
                .select_from(ExecutionAttempt)
                .where(
                    ExecutionAttempt.operation_ref.in_(
                        select(GatewayOperation.operation_ref).where(
                            GatewayOperation.task_ref == bound.task.task_ref
                        )
                    )
                )
            )
            == 0
        )
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.user_id == bound.owner.owner_id,
                AuditEvent.event_type == "catalog.metadata_listed",
            )
        )
        assert set(audit.detail) == {
            "request_id",
            "task_ref",
            "operation_ref",
            "action",
            "timestamp",
        }
        assert audit.detail["request_id"] == bound.request.request_id
        assert audit.detail["operation_ref"] == db.scalar(
            select(GatewayOperation.operation_ref).where(
                GatewayOperation.task_ref == bound.task.task_ref
            )
        )
    print(
        json.dumps(
            {
                "case": "catalog_persistence",
                "resources": 2,
                "metadata_only": True,
                "execution_attempts": 0,
                "timestamp_microseconds": 678901,
            }
        )
    )


@pytest.mark.parametrize(
    "change", ["missing", "purpose", "expired", "revoked", "inactive", "version"]
)
def test_mysql_catalog_authorization_fails_closed(catalog_db, change):
    resources = register(catalog_db)
    bound = bind(catalog_db, resources, consent=change != "missing")
    now = NOW
    if change == "purpose":
        bound.request = ToolRequest.model_validate_json(
            json.dumps({**bound.request.model_dump(mode="json"), "purpose": "answer_question"})
        )
    elif change == "expired":
        now += timedelta(minutes=10)
    elif change == "revoked":
        with bound.factory() as db:
            revoke_scoped_consent(
                db,
                owner=bound.owner,
                task_ref=bound.task.task_ref,
                consent_ref=bound.consent.consent_ref,
                now=NOW,
            )
    elif change == "inactive":
        with bound.factory() as db:
            deactivate_resource(
                db, owner=bound.owner, resource_ref=resources[0].resource_ref, now=NOW
            )
    elif change == "version":
        # Test-only mutation models a new version; no version-edit API is introduced.
        with bound.factory.begin() as db:
            db.execute(
                update(DocumentResource)
                .where(DocumentResource.resource_ref == resources[0].resource_ref)
                .values(version_ref="version_" + uuid4().hex)
            )
    reason = safe_denial(lambda: listing(bound, now=now))
    assert reason
    if change == "missing":
        assert bound.response.decision == "DENY"
    print(
        json.dumps({"case": "catalog_denied_" + change, "reason": reason, "metadata_returned": 0})
    )


@pytest.mark.parametrize("mismatch", ["resource", "purpose"])
def test_mysql_catalog_exact_consent_scope(catalog_db, mismatch):
    resources = register(catalog_db, ("doc_project_report", "doc_tax_2026"))
    bound = bind(catalog_db, resources, consent=False)
    selected = resources[:1] if mismatch == "resource" else resources
    if mismatch == "resource":
        with bound.factory() as db, pytest.raises(AgentIdentityError, match="INVALID_REQUEST"):
            create_scoped_consent(
                db,
                owner=bound.owner,
                task_ref=bound.task.task_ref,
                now=NOW,
                payload=ConsentCreate(
                    action=bound.request.action,
                    purpose=bound.request.purpose,
                    resource_ids=tuple(r.resource_ref for r in selected),
                    expires_at=NOW + timedelta(minutes=10),
                ),
            )
    else:
        with bound.factory() as db:
            create_scoped_consent(
                db,
                owner=bound.owner,
                task_ref=bound.task.task_ref,
                now=NOW,
                payload=ConsentCreate(
                    action=bound.request.action,
                    purpose=bound.request.purpose,
                    resource_ids=tuple(r.resource_ref for r in selected),
                    expires_at=NOW + timedelta(minutes=10),
                ),
            )
    request = bound.request
    if mismatch == "purpose":
        request = ToolRequest.model_validate_json(
            json.dumps({**request.model_dump(mode="json"), "purpose": "answer_question"})
        )
    with bound.factory() as db:
        response = authorize_request(db, token=bound.issued.token, request=request, now=NOW)
    assert response.decision == "DENY" and response.execution_status == "NOT_EXECUTED"
    assert response.result is None
    print(
        json.dumps(
            {
                "case": "catalog_exact_scope_" + mismatch,
                "reason": response.reason_code,
                "metadata_returned": 0,
            }
        )
    )


@pytest.mark.parametrize("operation", ["register", "deactivate", "lookup"])
def test_mysql_catalog_agent_cannot_manage(catalog_db, operation):
    resources = register(catalog_db)
    bound = bind(catalog_db, resources)
    with bound.factory() as db:
        agent = validate_agent_credential(
            db, token=bound.issued.token, task_ref=bound.task.task_ref, now=NOW
        )
    with bound.factory() as db, pytest.raises(AgentIdentityError, match="ROLE_FORBIDDEN"):
        if operation == "register":
            register_synthetic_resources(
                db, owner=agent, selection=FixtureRegistration(fixtures=("doc_schedule",)), now=NOW
            )
        elif operation == "deactivate":
            deactivate_resource(db, owner=agent, resource_ref=resources[0].resource_ref, now=NOW)
        else:
            lookup_resource(db, owner=agent, resource_ref=resources[0].resource_ref)


def test_mysql_catalog_owner_and_scope_isolation(catalog_db):
    factory, owner = catalog_db
    resources = register(catalog_db, ("doc_project_report", "doc_schedule"))
    bound = bind(catalog_db, resources[:1])
    assert tuple(r.resource_id for r in listing(bound).resources) == (resources[0].resource_ref,)
    other = OwnerContext(owner_id="catalog_other_" + uuid4().hex)
    with factory.begin() as db:
        db.add(User(id=other.owner_id))
    with factory() as db, pytest.raises(AgentIdentityError, match="NOT_FOUND"):
        lookup_resource(db, owner=other, resource_ref=resources[0].resource_ref)
    with factory() as db, pytest.raises(AgentIdentityError, match="NOT_FOUND"):
        lookup_resource(db, owner=owner, resource_ref="resource_" + "f" * 32)
    with pytest.raises(ValueError, match="trusted owner catalog"):
        bind((factory, other), resources[:1])
    assert counts((factory, other)) == 0


@pytest.mark.parametrize(
    "change",
    [
        "owner",
        "owner_storage",
        "resource",
        "version",
        "resource_shape",
        "version_shape",
        "type",
        "digest",
        "classification",
        "storage",
        "active",
        "timestamp",
    ],
)
def test_mysql_catalog_database_constraints(catalog_db, mysql_engine, change):
    resources = register(catalog_db)
    with catalog_db[0]() as db:
        row = db.get(DocumentResource, resources[0].resource_ref)
        values = {c.name: getattr(row, c.name) for c in DocumentResource.__table__.columns}
    values.update(resource_ref="resource_" + uuid4().hex, version_ref="version_" + uuid4().hex)
    changes = {
        "owner": {"owner_ref": "nonexistent_" + uuid4().hex},
        "owner_storage": {},
        "resource_shape": {"resource_ref": "path_not_resource"},
        "version_shape": {"version_ref": "filename_not_version"},
        "type": {"resource_type": "REAL_DOCUMENT"},
        "resource": {"resource_ref": resources[0].resource_ref},
        "version": {"version_ref": resources[0].version_ref},
        "digest": {"content_digest": "bad"},
        "classification": {"classification": "PUBLIC"},
        "storage": {"storage_reference": "../../personal.txt"},
        "active": {"active": 2},
        "timestamp": {"updated_at": NOW - timedelta(seconds=1)},
    }
    values.update(changes[change])
    # The original owner/storage uniqueness also applies; separate each tested constraint.
    if change not in ("owner", "storage", "owner_storage"):
        values["storage_reference"] = "ghost_demo_v1_doc_schedule"
    with mysql_engine.connect() as connection:
        tx = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO document_resources ("
                    + ",".join(values)
                    + ") VALUES ("
                    + ",".join(":" + k for k in values)
                    + ")"
                ),
                values,
            )
        tx.rollback()
    assert counts(catalog_db) == 1


def test_mysql_catalog_schema_and_database_failure(catalog_db, mysql_engine):
    schema = inspect(mysql_engine)
    assert {"owner_ref"} in [
        set(f["constrained_columns"]) for f in schema.get_foreign_keys("document_resources")
    ]
    assert {"owner_ref", "storage_reference"} in [
        set(u["column_names"]) for u in schema.get_unique_constraints("document_resources")
    ]
    assert any(i["column_names"] == ["owner_ref"] for i in schema.get_indexes("document_resources"))
    assert len(schema.get_check_constraints("document_resources")) >= 8
    with catalog_db[0]() as db:

        def failed(*args):
            raise OperationalError("redacted", {}, Exception("synthetic database unavailable"))

        event.listen(db, "before_commit", failed)
        with pytest.raises(AgentIdentityError, match="GATEWAY_UNAVAILABLE"):
            register_synthetic_resources(
                db,
                owner=catalog_db[1],
                selection=FixtureRegistration(fixtures=("doc_schedule",)),
                now=NOW,
            )
    assert counts(catalog_db) == 0


def overlap(engine, table, workers, function):
    """Barrier immediately before row-lock SQL: distinct live MySQL transactions overlap."""
    barrier, mutex = Barrier(workers), Lock()
    sessions = set()

    def observe(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("catalog-overlap")
            and table in statement
            and "FOR UPDATE" in statement
        ):
            if connection.info.get("catalog_barrier"):
                return
            connection.info["catalog_barrier"] = True
            session_id = connection.exec_driver_sql("SELECT CONNECTION_ID()").scalar_one()
            with mutex:
                sessions.add(session_id)
            barrier.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="catalog-overlap") as pool:
            futures = [pool.submit(function, i) for i in range(workers)]
            results = [f.result(timeout=20) for f in futures]
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(sessions) == workers
    return results


@pytest.mark.parametrize(
    "mode", ["registration", "listing", "deactivation", "owners", "version_conflict"]
)
def test_mysql_catalog_overlapping_sessions(catalog_db, mysql_engine, mode):
    factory, owner = catalog_db
    workers = 2 if mode == "version_conflict" else 8
    if mode in ("listing", "deactivation"):
        resources = register(catalog_db)
        bound = bind(catalog_db, resources)
        with factory() as db:
            original_version = db.get(GatewayTask, bound.task.task_ref).authorization_version
    other = OwnerContext(owner_id="catalog_other_" + uuid4().hex)
    if mode == "owners":
        with factory.begin() as db:
            db.add(User(id=other.owner_id))

    class ChangedStorage:
        def validate(self, name):
            alias, digest, display, classification = DEFAULT_STORAGE.validate(name)
            return alias, ("a" if digest[0] != "a" else "b") * 64, display, classification

    def run(index):
        try:
            if mode == "listing":
                return listing(bound).model_dump(mode="json")
            if mode == "deactivation":
                with factory() as db:
                    return deactivate_resource(
                        db, owner=owner, resource_ref=resources[0].resource_ref, now=NOW
                    ).active
            selected = (factory, other) if mode == "owners" and index % 2 else catalog_db
            kwargs = {"storage": ChangedStorage()} if mode == "version_conflict" and index else {}
            return register(selected, **kwargs)[0].resource_ref
        except AgentIdentityError as error:
            return error.code

    results = overlap(mysql_engine, "gateway_tasks" if mode == "listing" else "users", workers, run)
    conflicts = results.count("RESOURCE_CONFLICT")
    if mode == "registration":
        assert len(set(results)) == counts(catalog_db) == 1
    elif mode == "listing":
        assert all(r == results[0] for r in results)
        assert results[0] == {
            "resources": [
                {"resource_id": resources[0].resource_ref, "version_ref": resources[0].version_ref}
            ]
        }
    elif mode == "deactivation":
        assert results == [False] * workers
        with factory() as db:
            assert (
                db.get(GatewayTask, bound.task.task_ref).authorization_version
                == original_version + 1
            )
        assert safe_denial(lambda: register(catalog_db)) == "RESOURCE_INACTIVE"
        assert safe_denial(lambda: listing(bound))
    elif mode == "owners":
        assert len(set(results)) == 2
        assert counts(catalog_db) == counts((factory, other)) == 1
    else:
        assert conflicts == 1 and counts(catalog_db) == 1
    print(
        json.dumps(
            {
                "case": "catalog_concurrent_" + mode,
                "requests": workers,
                "overlapping_sessions": workers,
                "successful": workers - conflicts,
                "conflicts": conflicts,
                "owner_resource_count": counts(catalog_db),
                "deadlocks_or_timeouts": 0,
                "active": mode != "deactivation",
            }
        )
    )


@pytest.mark.parametrize("kind", ["deactivation", "consent"])
def test_mysql_catalog_revocation_blocks_listing(catalog_db, mysql_engine, monkeypatch, kind):
    import app.services.document_catalog as catalog
    import app.services.scoped_consent as policy

    resources = register(catalog_db)
    bound = bind(catalog_db, resources)
    locked, attempted, release = Event(), Event(), Event()
    module, method = (
        (catalog, "_owned_resource") if kind == "deactivation" else (policy, "_owned_task")
    )
    original = getattr(module, method)

    def hold(*args, **kwargs):
        row = original(*args, **kwargs)
        locked.set()
        assert release.wait(10)
        return row

    def observe(connection, cursor, statement, parameters, context, many):
        if (
            current_thread().name.startswith("catalog-reader")
            and "gateway_tasks" in statement
            and "FOR UPDATE" in statement
        ):
            attempted.set()

    def writer():
        with bound.factory() as db:
            if kind == "deactivation":
                deactivate_resource(
                    db, owner=bound.owner, resource_ref=resources[0].resource_ref, now=NOW
                )
            else:
                revoke_scoped_consent(
                    db,
                    owner=bound.owner,
                    task_ref=bound.task.task_ref,
                    consent_ref=bound.consent.consent_ref,
                    now=NOW,
                )

    monkeypatch.setattr(module, method, hold)
    event.listen(mysql_engine, "before_cursor_execute", observe)
    try:
        with (
            ThreadPoolExecutor(max_workers=1) as writers,
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="catalog-reader") as readers,
        ):
            write = writers.submit(writer)
            assert locked.wait(5)
            read = readers.submit(lambda: safe_denial(lambda: listing(bound)))
            try:
                assert attempted.wait(5)
                with pytest.raises(TimeoutError):
                    read.result(timeout=0.2)
            finally:
                release.set()
            write.result(10)
            reason = read.result(10)
    finally:
        release.set()
        event.remove(mysql_engine, "before_cursor_execute", observe)
    print(
        json.dumps(
            {
                "case": "catalog_revocation_" + kind,
                "overlapping_sessions": 2,
                "writer_committed": 1,
                "listing_rejected": 1,
                "reason": reason,
                "blocked_before_commit": True,
                "metadata_returned": 0,
                "deadlocks_or_timeouts": 0,
            }
        )
    )


def test_mysql_catalog_restart_writer(catalog_db):
    resources = register(catalog_db, ("doc_project_report", "doc_tax_2026"))
    bound = bind(catalog_db, resources)
    expected = listing(bound).model_dump(mode="json")
    with bound.factory() as db:
        deactivate_resource(db, owner=bound.owner, resource_ref=resources[1].resource_ref, now=NOW)
    print(
        json.dumps(
            {
                "catalog_restart_expected": {
                    "owner": bound.owner.owner_id,
                    "resources": [r.model_dump(mode="json") for r in resources],
                    "metadata": expected,
                    "inactive_ref": resources[1].resource_ref,
                    "task_ref": bound.task.task_ref,
                    "request": bound.request.model_dump(mode="json"),
                }
            }
        )
    )


def test_mysql_catalog_restart_reader(mysql_engine):
    expected = json.loads(Path(os.environ["CATALOG_RESTART_EXPECTED"]).read_text())
    factory = sessionmaker(mysql_engine, expire_on_commit=False, autoflush=False)
    owner = OwnerContext(owner_id=expected["owner"])
    with factory() as db:
        rows = list(
            db.scalars(select(DocumentResource).where(DocumentResource.owner_ref == owner.owner_id))
        )
        assert len(rows) == 2
        for row in rows:
            old = next(r for r in expected["resources"] if r["resource_ref"] == row.resource_ref)
            assert (
                row.version_ref == old["version_ref"]
                and row.classification == old["classification"]
            )
            assert row.active == (row.resource_ref != expected["inactive_ref"])
            assert row.created_at.isoformat() == old["created_at"].replace("Z", "+00:00")
            fixture = (
                "doc_tax_2026" if row.classification == "PRIVATE_ORIGINAL" else "doc_project_report"
            )
            alias, digest, _, _ = DEFAULT_STORAGE.validate(fixture)
            assert row.storage_reference == alias and row.content_digest == digest
    assert register((factory, owner))[0].resource_ref == expected["resources"][0]["resource_ref"]
    with factory() as db:
        issued = issue_agent_credential(db, owner=owner, task_ref=expected["task_ref"], now=NOW)
    bound = SimpleNamespace(
        factory=factory,
        issued=issued,
        request=ToolRequest.model_validate_json(json.dumps(expected["request"])),
    )
    reason = safe_denial(lambda: listing(bound))
    with factory() as db:
        active = lookup_resource(
            db, owner=owner, resource_ref=expected["resources"][0]["resource_ref"]
        )
    fresh = bind((factory, owner), (active,))
    assert len(listing(fresh).resources) == 1
    print(
        json.dumps(
            {
                "case": "catalog_restart_verified",
                "resources": 2,
                "identity_preserved": True,
                "inactive_preserved": True,
                "integrity_preserved": True,
                "fresh_authorized_listing": 1,
                "listing_denied": reason,
            }
        )
    )
