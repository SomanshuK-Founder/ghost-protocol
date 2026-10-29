"""Only registered synthetic UTF-8 text, invoked by the trusted shared dispatcher."""

from app.gateway_contracts import DocumentFileResult
from app.services.fixture_storage import FIXTURES, STORAGE_REFERENCES, FixtureError, FixtureStorage
from app.services.synthetic_executor import ExecutionInput, ExecutionOutcome

READ_ERRORS = frozenset(
    {
        "READ_RESOURCE_INVALID",
        "READ_PATH_UNSAFE",
        "READ_SIZE_LIMIT",
        "READ_INTEGRITY_FAILURE",
        "READ_ENCODING_INVALID",
        "READ_CONTENT_INVALID",
        "READ_PLATFORM_UNSUPPORTED",
    }
)


class SyntheticDocumentReader:
    def __init__(self, storage: FixtureStorage | None = None, *, max_bytes=32768):
        if type(max_bytes) is not int or not 1 <= max_bytes <= 65536:
            raise ValueError("Synthetic read limit must be 1..65536 bytes")
        self._storage = storage or FixtureStorage()
        self._max_bytes = max_bytes

    def execute(self, request: ExecutionInput) -> ExecutionOutcome:
        document = request.document if isinstance(request, ExecutionInput) else None
        if (
            document is None
            or request.action != "files.read"
            or request.context.mode != "SYNTHETIC_READ"
            or document.resource_ref != request.arguments.resource_id
            or document.storage_reference not in STORAGE_REFERENCES
            or document.classification
            != FIXTURES[document.storage_reference.removeprefix("ghost_demo_v1_")][2]
        ):
            return ExecutionOutcome("FAILED", sanitized_error_code="READ_RESOURCE_INVALID")
        try:
            raw = self._storage._read_synthetic(
                document.storage_reference, document.content_digest, limit=self._max_bytes
            )
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeError:
                raise FixtureError("READ_ENCODING_INVALID") from None
            if text.startswith("\ufeff"):
                raise FixtureError("READ_ENCODING_INVALID")
            if len(text) > 20000:
                raise FixtureError("READ_SIZE_LIMIT")
            if any((ord(c) < 32 and c not in "\t\r\n") or 127 <= ord(c) < 160 for c in text):
                raise FixtureError("READ_CONTENT_INVALID")
            return ExecutionOutcome(
                "SUCCEEDED",
                DocumentFileResult(
                    resource_id=document.resource_ref,
                    version_ref=request.version_ref,
                    text=text,
                ),
            )
        except FixtureError as error:
            code = error.code if error.code in READ_ERRORS else "READ_PATH_UNSAFE"
            return ExecutionOutcome("FAILED", sanitized_error_code=code)
