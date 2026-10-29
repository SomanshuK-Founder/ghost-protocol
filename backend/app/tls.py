"""Per-client CA trust selected by trusted composition, never request/model data."""

import os
import ssl
import stat
from pathlib import Path

import certifi


class TLSConfigurationError(ValueError):
    """Sanitized configuration failure without certificate bytes or local paths."""


def tls_verification(
    *, openshell: bool = False, ca_bundle: str | Path | None = None
) -> bool | ssl.SSLContext:
    if type(openshell) is not bool or (not openshell and ca_bundle is not None):
        raise TLSConfigurationError("Invalid trusted TLS configuration")
    if not openshell:
        return True  # Preserve HTTPX's existing certifi trust and trust_env=False behavior.

    selected = ca_bundle if ca_bundle is not None else os.environ.get("SSL_CERT_FILE")
    try:
        if not isinstance(selected, (str, Path)) or not str(selected):
            raise ValueError
        path = Path(selected)
        if not path.is_absolute() or len(str(path)) > 4096:
            raise ValueError
        # Check/read the same handle; reject special files without blocking on a FIFO.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 1024 * 1024:
                raise ValueError
            bundle = stream.read(1024 * 1024 + 1)
        if len(bundle) > 1024 * 1024 or b"PRIVATE KEY" in bundle:
            raise ValueError
        # Retain the same public roots as normal HTTPX, adding only the selected bundle.
        context = ssl.create_default_context(cafile=certifi.where())
        context.load_verify_locations(cadata=bundle.decode("ascii"))
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise ValueError
        return context
    except (OSError, ValueError, UnicodeError):
        raise TLSConfigurationError("Trusted CA bundle unavailable or invalid") from None
