"""SC4: rules-only diagnosis against the 2,000-session golden set (PRD 17/18)."""

from __future__ import annotations

import pytest
from agentlens.eval import golden
from agentlens.eval.golden import TOTAL_SESSIONS, run_golden


@pytest.fixture(scope="module")
def result(tmp_path_factory):  # type: ignore[no-untyped-def]
    return run_golden(tmp_path_factory.mktemp("golden"), regenerate=True)


def test_golden_set_is_2000_sessions():
    assert TOTAL_SESSIONS == 2000 and sum(s.sessions for s in golden.SEGMENTS) == 2000


def test_sc4_thresholds_met(result):
    assert result.precision >= golden.THRESHOLDS["precision"], result
    assert result.recall >= golden.THRESHOLDS["recall"], result
    assert result.passed


def test_every_blocker_is_evaluated(result):
    covered = {b for b, s in result.per_blocker.items() if s.support > 0}
    assert covered == {f"B{i:02d}" for i in range(1, 17)}
    for blocker, score in result.per_blocker.items():
        assert (score.recall or 0) >= 0.8, (blocker, score)
