"""Explicit synthetic-fixture integrity checks; never a document-reading tool."""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MANIFEST_DIGEST = "029e5f5dd7e822c25bc2a111e39210da640f40b02248fedbf34ae2a6311e851e"
DEFAULT_ROOT = Path(__file__).resolve().parents[4] / "fixtures/ghost_demo"
# Backend-approved selection and classification; fixture owner labels grant no authority.
FIXTURES = {
    "doc_tax_2026": (
        "documents/private/tax_statement_2026.txt",
        "Synthetic tax statement",
        "PRIVATE_ORIGINAL",
        "restricted_financial",
    ),
    "doc_bank_oct": (
        "documents/private/bank_statement_demo.txt",
        "Synthetic bank statement",
        "PRIVATE_ORIGINAL",
        "restricted_financial",
    ),
    "doc_personal_notes": (
        "documents/private/personal_notes.txt",
        "Synthetic personal notes",
        "PRIVATE_ORIGINAL",
        "private",
    ),
    "doc_project_report": (
        "documents/shareable/project_report.txt",
        "Synthetic project report",
        "SHAREABLE",
        "shareable",
    ),
    "doc_meeting_oct": (
        "documents/shareable/meeting_summary.txt",
        "Synthetic meeting summary",
        "SHAREABLE",
        "shareable",
    ),
    "doc_schedule": (
        "documents/shareable/project_schedule.txt",
        "Synthetic project schedule",
        "SHAREABLE",
        "shareable",
    ),
}
STORAGE_REFERENCES = tuple("ghost_demo_v1_" + key for key in FIXTURES)
MAX_FIXTURE_BYTES = 65536


class FixtureError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or "\\" in value or ":" in value or "\x00" in value:
        raise FixtureError("FIXTURE_PATH_INVALID")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(p in (".", "..") for p in value.split("/")):
        raise FixtureError("FIXTURE_PATH_INVALID")
    if str(path) != value:
        raise FixtureError("FIXTURE_PATH_INVALID")
    return path


def _identity(info):
    return info.st_dev, info.st_ino


def _not_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
    ):
        raise FixtureError("FIXTURE_PATH_INVALID")
    return info


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FixtureError("FIXTURE_MANIFEST_INVALID")
        result[key] = value
    return result


@dataclass(frozen=True)
class FixtureStorage:
    root: Path = DEFAULT_ROOT
    manifest_digest: str = MANIFEST_DIGEST

    def _read_synthetic(self, storage_reference: str, expected_digest: str, *, limit=32768):
        """Executor-only bytes, bounded and integrity-checked; never accept an agent path."""
        from app.services.secure_fixture_io import synthetic_bytes

        if storage_reference not in STORAGE_REFERENCES:
            raise FixtureError("READ_PATH_UNSAFE")
        if (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(c not in "0123456789abcdef" for c in expected_digest)
        ):
            raise FixtureError("READ_INTEGRITY_FAILURE")
        fixture = storage_reference.removeprefix("ghost_demo_v1_")
        content = synthetic_bytes(self.root, FIXTURES[fixture][0], limit)
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise FixtureError("READ_INTEGRITY_FAILURE")
        return content

    def _verified_bytes(self, relative: str, *, metadata=False):
        """Bounded hashing only for selected fixtures; raw document bytes never leave here."""
        try:
            allowed = (
                ("MANIFEST.json", "fixtures/resources.json")
                if metadata
                else tuple(value[0] for value in FIXTURES.values())
            )
            if relative not in allowed:
                raise FixtureError("FIXTURE_SELECTION_INVALID")
            parts = relative_path(relative).parts
            if (
                not self.root.is_absolute()
                or ".." in self.root.parts
                or str(self.root).startswith(("\\\\", "//"))
            ):
                raise FixtureError("FIXTURE_PATH_INVALID")
            # Reject reparse points in the configured root and every selected component.
            current = Path(self.root.anchor)
            paths = []
            for part in (*self.root.parts[1:], *parts):
                current /= part
                paths.append((current, _not_link(current)))
            path, before = paths[-1]
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise FixtureError("FIXTURE_PATH_INVALID")
            if before.st_size > MAX_FIXTURE_BYTES:
                raise FixtureError("FIXTURE_TOO_LARGE")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if _identity(opened) != _identity(before) or opened.st_nlink != 1:
                    raise FixtureError("FIXTURE_PATH_INVALID")
                for component, info in paths:
                    if _identity(_not_link(component)) != _identity(info):
                        raise FixtureError("FIXTURE_PATH_INVALID")
                digest, count, chunks = hashlib.sha256(), 0, []
                while chunk := stream.read(8192):
                    count += len(chunk)
                    if count > MAX_FIXTURE_BYTES:
                        raise FixtureError("FIXTURE_TOO_LARGE")
                    digest.update(chunk)
                    if metadata:
                        chunks.append(chunk)
                after = os.fstat(stream.fileno())
                if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise FixtureError("FIXTURE_CHANGED")
            return digest.hexdigest(), b"".join(chunks) if metadata else None
        except (OSError, ValueError, TypeError):
            raise FixtureError("FIXTURE_PATH_INVALID") from None

    def validate(self, fixture: str):
        if fixture not in FIXTURES:
            raise FixtureError("FIXTURE_SELECTION_INVALID")
        try:
            digest, raw = self._verified_bytes("MANIFEST.json", metadata=True)
            if digest != self.manifest_digest:
                raise FixtureError("FIXTURE_MANIFEST_INVALID")
            manifest = json.loads(raw, object_pairs_hook=_object)
            if (
                set(manifest) != {"dataset_version", "files"}
                or manifest["dataset_version"] != "1.0"
            ):
                raise FixtureError("FIXTURE_MANIFEST_INVALID")
            if not isinstance(manifest["files"], list) or not 1 <= len(manifest["files"]) <= 100:
                raise FixtureError("FIXTURE_MANIFEST_INVALID")
            entries = {}
            for item in manifest["files"]:
                if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                    raise FixtureError("FIXTURE_MANIFEST_INVALID")
                path = str(relative_path(item["path"]))
                value = item["sha256"]
                if (
                    path in entries
                    or not isinstance(value, str)
                    or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)
                ):
                    raise FixtureError("FIXTURE_MANIFEST_INVALID")
                entries[path] = value
            digest, raw = self._verified_bytes("fixtures/resources.json", metadata=True)
            if digest != entries.get("fixtures/resources.json"):
                raise FixtureError("FIXTURE_MANIFEST_INVALID")
            catalog = json.loads(raw, object_pairs_hook=_object)
            if set(catalog) != {"synthetic", "resources"} or catalog["synthetic"] is not True:
                raise FixtureError("FIXTURE_MANIFEST_INVALID")
            records = catalog["resources"]
            if not isinstance(records, list) or len(records) != len(FIXTURES):
                raise FixtureError("FIXTURE_MANIFEST_INVALID")
            seen = set()
            for item in records:
                if set(item) != {"resource_id", "relative_path", "classification", "owner_ref"}:
                    raise FixtureError("FIXTURE_MANIFEST_INVALID")
                key = item["resource_id"]
                if key not in FIXTURES or key in seen:
                    raise FixtureError("FIXTURE_MANIFEST_INVALID")
                expected = FIXTURES[key]
                if (
                    item["relative_path"] != expected[0]
                    or item["classification"] != expected[3]
                    or not isinstance(item["owner_ref"], str)
                ):
                    raise FixtureError("FIXTURE_MANIFEST_INVALID")
                seen.add(key)
            relative, display, classification, _ = FIXTURES[fixture]
            if PurePosixPath(relative).suffix != ".txt":
                raise FixtureError("FIXTURE_TYPE_INVALID")
            digest, _ = self._verified_bytes(relative)
            if digest != entries.get(relative):
                raise FixtureError("FIXTURE_DIGEST_MISMATCH")
            return "ghost_demo_v1_" + fixture, digest, display, classification
        except (KeyError, ValueError, TypeError, RecursionError):
            raise FixtureError("FIXTURE_MANIFEST_INVALID") from None
