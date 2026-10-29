"""Opt-in sequential six-call smoke suite. Normal pytest skips it without reading .env."""

import asyncio
import os
from pathlib import Path

import pytest

from app.llm.config import NebiusSettings
from app.llm.live_validation import (
    LiveExpectations,
    load_live_settings,
    render_live_report,
    run_live_validation,
)


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("GHOST_RUN_NEBIUS_LIVE") != "1",
    reason="Paid inference disabled; explicit user approval and operator opt-in required",
)
def test_nebius_live() -> None:
    # Do not enable until the user approves the first live request.
    # Exact expectations are independent public values supplied by the operator.
    required = ("GHOST_LIVE_EXPECT_BASE_URL", "GHOST_LIVE_EXPECT_SUPER", "GHOST_LIVE_EXPECT_NANO")
    if any(not os.environ.get(name) for name in required):
        pytest.fail("Live expectations must be supplied explicitly", pytrace=False)
    try:
        expectations = LiveExpectations(
            base_url=os.environ[required[0]],
            model_super=os.environ[required[1]],
            model_nano=os.environ[required[2]],
        )
        settings: NebiusSettings = load_live_settings(env_file=Path(".env"))
        results = asyncio.run(run_live_validation(settings, expectations, approved=True))
    except Exception:
        pytest.fail(
            "Live preflight failed; check credentials, models, endpoint, and logging", pytrace=False
        )
    Path("docs/member_b/B1_VALIDATION_REPORT.md").write_text(
        render_live_report(results, settings.base_url), encoding="utf-8"
    )
    if any(result.status != "SUCCEEDED" for result in results):
        pytest.fail(
            "Live probes did not all succeed; inspect the sanitized validation report",
            pytrace=False,
        )
