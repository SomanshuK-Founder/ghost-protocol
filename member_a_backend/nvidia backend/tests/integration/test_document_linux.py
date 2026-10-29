"""Step 25 Linux-native filesystem probes, only in the approved non-root container."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from app.gateway_contracts import FileArguments
from app.services.document_reader import SyntheticDocumentReader
from app.services.fixture_storage import FixtureError, FixtureStorage
from app.services.synthetic_executor import DocumentBinding, ExecutionContext, ExecutionInput
from tests.test_scoped_consent import NOW

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session", autouse=True)
def isolated_linux_only():
    if os.getenv("GHOST_LINUX_VALIDATION") != "ghost-document-validation" or os.name != "posix":
        pytest.skip("Requires the approved isolated Linux filesystem runner")
    assert os.geteuid() == 1000
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    assert int(status["CapEff"].strip(), 16) == 0 and status["NoNewPrivs"].strip() == "1"
    assert not any(
        key in os.environ for key in ("MYSQL_PASSWORD", "API_BEARER_TOKEN", "NEBIUS_API_KEY")
    )


@pytest.mark.parametrize(
    "case",
    [
        "normal",
        "traversal",
        "absolute",
        "symlink",
        "hardlink",
        "nonregular",
        "oversize",
        "replacement",
        "digest",
        "encoding",
        "root_escape",
        "permission",
    ],
)
def test_linux_document_file_safety(tmp_path, monkeypatch, case):
    import app.services.secure_fixture_io as io

    root = tmp_path / "dedicated_synthetic_root"
    file = root / "documents/shareable/project_report.txt"
    file.parent.mkdir(parents=True)
    content = b"SYNTHETIC Linux fixture marker; never print document bytes."
    file.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    store = FixtureStorage(root=root)
    reference = "ghost_demo_v1_doc_project_report"
    limit = 32768
    if case == "traversal":
        reference = "../documents/shareable/project_report.txt"
    elif case == "absolute":
        reference = str(file)
    elif case == "symlink":
        outside = tmp_path / "synthetic_outside.txt"
        outside.write_bytes(content)
        file.unlink()
        file.symlink_to(outside)
    elif case == "hardlink":
        os.link(file, tmp_path / "synthetic_link.txt")
    elif case == "nonregular":
        file.unlink()
        os.mkfifo(file)
    elif case == "oversize":
        limit = 8
    elif case == "replacement":
        original = io._read_bounded

        def replace(stream, size):
            file.rename(file.with_name("synthetic_moved.txt"))
            file.write_bytes(b"SYNTHETIC replacement")
            return original(stream, size)

        monkeypatch.setattr(io, "_read_bounded", replace)
    elif case == "digest":
        digest = "0" * 64
    elif case == "encoding":
        content = b"\xff\xfeSYNTHETIC invalid UTF8"
        file.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
    elif case == "root_escape":
        target = root / "documents"
        target.rename(tmp_path / "synthetic_moved_directory")
        target.symlink_to(tmp_path / "synthetic_moved_directory", target_is_directory=True)
    elif case == "permission":
        file.chmod(0)
    try:
        if case == "normal":
            assert hashlib.sha256(store._read_synthetic(reference, digest)).hexdigest() == digest
        elif case == "encoding":
            binding = DocumentBinding(
                "resource_" + "a" * 32, "linux_owner", reference, digest, "SHAREABLE"
            )
            value = ExecutionInput(
                "op_linux",
                "task_linux",
                "req_linux",
                "key_linux",
                "a" * 64,
                "files.read",
                FileArguments(resource_id=binding.resource_ref),
                "version_" + "b" * 32,
                ExecutionContext("attempt_linux", NOW, "SYNTHETIC_READ"),
                binding,
            )
            result = SyntheticDocumentReader(store).execute(value)
            assert result.status == "FAILED" and result.result is None
            assert result.sanitized_error_code == "READ_ENCODING_INVALID"
        else:
            with pytest.raises(FixtureError):
                store._read_synthetic(reference, digest, limit=limit)
    finally:
        if case == "permission":
            file.chmod(0o600)
    print(
        json.dumps(
            {
                "case": "linux_" + case,
                "verified": True,
                "euid": os.geteuid(),
                "content_printed": False,
                "unexpected_content_returned": False,
            }
        )
    )
