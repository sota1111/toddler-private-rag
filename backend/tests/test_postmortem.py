"""SOT-1484 follow-up: tests for the deterministic incident RCA + improvement-proposal generator.

These exercise the PURE logic in ``backend/remediation_function/postmortem.py`` (signal
classification, per-signal causes/proposals, severity, remediation summary, markdown rendering).
No GCP access and no LLM — the generator is rule-based, matching the design principle that the
failure path stays deterministic. Runs in the backend CI image (functions_framework not imported).
"""
import datetime
import os
import sys

_REMEDIATION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "remediation_function"
)
if _REMEDIATION_DIR not in sys.path:
    sys.path.insert(0, _REMEDIATION_DIR)

import postmortem as P  # noqa: E402
import remediation as R  # noqa: E402

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)


def _incident(policy="", condition="", service="toddler-private-rag-backend"):
    return R.Incident(state="open", service=service, policy=policy, condition=condition)


# --- signal classification -------------------------------------------------------
def test_classify_5xx():
    inc = _incident(policy="Cloud Run 5xx error rate high (SOT-1400)")
    assert P.classify_signal(inc) == P.SIGNAL_5XX


def test_classify_latency():
    inc = _incident(policy="Cloud Run request latency high", condition="p99 request latency")
    assert P.classify_signal(inc) == P.SIGNAL_LATENCY


def test_classify_llm_error():
    inc = _incident(policy="LLM error rate high (SOT-1472)")
    assert P.classify_signal(inc) == P.SIGNAL_LLM_ERROR


def test_classify_grounding():
    inc = _incident(policy="LLM grounding degradation rate high (SOT-1470 D3)")
    assert P.classify_signal(inc) == P.SIGNAL_GROUNDING


def test_classify_unknown():
    inc = _incident(policy="some unrelated policy", condition="whatever")
    assert P.classify_signal(inc) == P.SIGNAL_UNKNOWN


# --- analyze_incident ------------------------------------------------------------
def test_analyze_populates_causes_and_proposals():
    pm = P.analyze_incident(_incident(policy="5xx error rate high"), now=NOW)
    assert pm.signal == P.SIGNAL_5XX
    assert pm.title
    assert len(pm.probable_causes) >= 1
    assert len(pm.improvement_proposals) >= 1
    assert pm.runbooks
    assert pm.generator == "deterministic"
    assert pm.generated_at == NOW


def test_analyze_unknown_signal_still_yields_postmortem():
    pm = P.analyze_incident(_incident(policy="mystery"), now=NOW)
    assert pm.signal == P.SIGNAL_UNKNOWN
    assert pm.severity == "unknown"
    assert pm.probable_causes and pm.improvement_proposals


def test_analyze_incorporates_rollback_result():
    result = R.RemediationResult(
        service="toddler-private-rag-backend",
        action="rolled_back",
        reason="rolled back",
        current_revision="rev-2",
        target_revision="rev-1",
    )
    pm = P.analyze_incident(_incident(policy="latency high"), remediation=result, now=NOW)
    assert pm.severity == "high"  # a rollback escalates severity
    assert "rev-2 -> rev-1" in pm.remediation_summary


def test_analyze_skipped_rollback_summary():
    result = R.RemediationResult(
        service="svc", action="skipped", reason="cooldown active"
    )
    pm = P.analyze_incident(_incident(policy="5xx"), remediation=result, now=NOW)
    assert "skipped by guardrails" in pm.remediation_summary
    assert "cooldown active" in pm.remediation_summary


def test_analyze_without_remediation():
    pm = P.analyze_incident(_incident(policy="5xx"), now=NOW)
    assert "No remediation attempted" in pm.remediation_summary


# --- severity --------------------------------------------------------------------
def test_severity_5xx_is_high():
    pm = P.analyze_incident(_incident(policy="5xx error"), now=NOW)
    assert pm.severity == "high"


def test_severity_latency_is_medium_without_rollback():
    pm = P.analyze_incident(_incident(policy="latency high"), now=NOW)
    assert pm.severity == "medium"


# --- serialization / rendering ---------------------------------------------------
def test_as_dict_is_json_friendly():
    d = P.analyze_incident(_incident(policy="5xx"), now=NOW).as_dict()
    assert d["signal"] == P.SIGNAL_5XX
    assert isinstance(d["probable_causes"], list)
    assert isinstance(d["improvement_proposals"], list)
    assert d["generated_at"] == NOW.isoformat()
    assert d["generator"] == "deterministic"


def test_render_markdown_contains_sections():
    pm = P.analyze_incident(_incident(policy="LLM error rate high"), now=NOW)
    md = P.render_markdown(pm)
    assert "# Incident Postmortem" in md
    assert "## Probable root causes" in md
    assert "## Improvement proposals" in md
    assert "## Runbooks" in md
    # every proposal appears in the rendered doc
    for proposal in pm.improvement_proposals:
        assert proposal in md
