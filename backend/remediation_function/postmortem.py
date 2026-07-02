"""SOT-1484 follow-up: deterministic incident root-cause analysis (RCA) + improvement proposals.

Context: SOT-1480 added an autonomous runtime rollback (``remediation.py``). A Cloud Monitoring
alert (5xx / latency / LLM error / grounding degradation, see ``infra/terraform/monitoring.tf``)
fires a webhook that hits the remediation Cloud Run service; ``decide_and_rollback`` makes a
deterministic, guard-railed rollback decision.

Earlier PLAN work (SOT-1484) intentionally *excluded* automatic postmortem generation, arguing the
failure path should not contain a hallucination-prone generative step. A human correction
(2026-07-02: 「原因分析と改善提案までは実行できるようにしてください」) reversed that: we now DO
generate root-cause analysis and improvement proposals automatically — but we keep the design
principle by making the generation **deterministic and rule-based** (no LLM in the failure path).

This module maps an :class:`~remediation.Incident` (plus the remediation result, if any) to a
structured :class:`Postmortem` — probable root causes, concrete improvement proposals, and the
relevant runbook links — keyed on the alert signal. It is pure and import-safe (no GCP client, no
``functions_framework``), so it runs in the backend CI image and is fully unit-testable. The HTTP
wrapper (``main.py``) invokes it after the rollback decision and emits it in the response / audit log.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import List, Optional

try:  # runs both as a package-relative import (tests add the dir to sys.path) and standalone
    from remediation import Incident, RemediationResult
except ImportError:  # pragma: no cover - defensive; the module dir is on sys.path in practice
    from .remediation import Incident, RemediationResult  # type: ignore


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# --- Signal knowledge base -------------------------------------------------------
# Each alert signal maps to its human title, probable root causes, concrete improvement
# proposals, and the runbook(s) an on-call human should consult. This is a *deterministic*
# knowledge base — no generative model is consulted, so the failure path stays predictable.
SIGNAL_5XX = "5xx"
SIGNAL_LATENCY = "latency"
SIGNAL_LLM_ERROR = "llm_error"
SIGNAL_GROUNDING = "grounding_degraded"
SIGNAL_UNKNOWN = "unknown"


@dataclass(frozen=True)
class _SignalKB:
    title: str
    probable_causes: List[str]
    improvement_proposals: List[str]
    runbooks: List[str]


_KB: dict = {
    SIGNAL_5XX: _SignalKB(
        title="Cloud Run 5xx error rate high",
        probable_causes=[
            "A recent deploy introduced a regression (unhandled exception / bad config).",
            "A downstream dependency (Firestore / Vertex AI / Cloud Vision) is failing or throttling.",
            "Missing or invalid environment variable / secret after a config change.",
        ],
        improvement_proposals=[
            "Add or tighten a smoke test on the release path so a 5xx regression fails CI before deploy.",
            "Add request-level structured error logging to attribute 5xx to a specific route/dependency.",
            "Confirm the canary rollback threshold catches this failure mode; adjust if it did not.",
        ],
        runbooks=["docs/runbook-rollback.md", "docs/runbook-operations.md"],
    ),
    SIGNAL_LATENCY: _SignalKB(
        title="Cloud Run p99 request latency high",
        probable_causes=[
            "Cold starts (min-instances=0) under bursty traffic.",
            "Slow Vertex AI / grounding calls dominating request time.",
            "An N+1 or unindexed Firestore query on a hot path.",
        ],
        improvement_proposals=[
            "Consider a small min-instances floor for the latency-sensitive service.",
            "Add a timeout + deterministic fallback around slow LLM/grounding calls (already partially in ai_client).",
            "Add a p99 latency budget check to load/e2e so regressions surface pre-deploy.",
        ],
        runbooks=["docs/runbook-operations.md"],
    ),
    SIGNAL_LLM_ERROR: _SignalKB(
        title="LLM (Gemini) call failure rate high",
        probable_causes=[
            "Vertex AI quota exhaustion or rate limiting.",
            "An invalid / deprecated GEMINI_MODEL id after a model bump.",
            "Auth / credential expiry for the Vertex AI call path.",
        ],
        improvement_proposals=[
            "Pin and validate GEMINI_MODEL in a pre-deploy check so a bad model id fails CI.",
            "Add retry-with-backoff around transient Vertex AI errors before falling back.",
            "Alert on quota approaching limits, not just on failures, to act before the outage.",
        ],
        runbooks=["docs/runbook-operations.md", "docs/runbook-rollback.md"],
    ),
    SIGNAL_GROUNDING: _SignalKB(
        title="LLM grounding degradation rate high",
        probable_causes=[
            "Grounded search backend (Vertex AI Search / grounding) is unavailable or throttled.",
            "Empty or stale retrieval index causing grounded requests to return no sources.",
            "A prompt / API change broke the grounded request shape, forcing the non-grounded fallback.",
        ],
        improvement_proposals=[
            "Add an index freshness / non-empty check to the evaluation-gate so an empty index fails CI.",
            "Verify refusal behaviour holds (test_rag_refusal_on_empty_index) — answers must not be fabricated.",
            "Monitor the grounded-vs-fallback ratio as an SLI and alert before it dominates.",
        ],
        runbooks=["docs/runbook-operations.md"],
    ),
    SIGNAL_UNKNOWN: _SignalKB(
        title="Unclassified incident",
        probable_causes=[
            "The alert policy/condition did not match a known signal; manual triage required.",
        ],
        improvement_proposals=[
            "Extend the postmortem signal map to cover this alert policy so future incidents auto-classify.",
        ],
        runbooks=["docs/runbook-operations.md"],
    ),
}


def classify_signal(incident: Incident) -> str:
    """Deterministically classify an incident into a known signal from its policy/condition text."""
    text = f"{incident.policy} {incident.condition}".lower()
    if "grounding" in text or "grounded" in text:
        return SIGNAL_GROUNDING
    if "llm" in text or "gemini" in text:
        return SIGNAL_LLM_ERROR
    if "latency" in text or "p99" in text:
        return SIGNAL_LATENCY
    if "5xx" in text or "error rate" in text or "error" in text:
        return SIGNAL_5XX
    return SIGNAL_UNKNOWN


def _severity(signal: str, remediation: Optional[RemediationResult]) -> str:
    """A coarse, deterministic severity: rolled-back incidents are the most severe."""
    if remediation is not None and remediation.action == "rolled_back":
        return "high"
    if signal in {SIGNAL_5XX, SIGNAL_LLM_ERROR}:
        return "high"
    if signal == SIGNAL_UNKNOWN:
        return "unknown"
    return "medium"


def _remediation_summary(remediation: Optional[RemediationResult]) -> str:
    if remediation is None:
        return "No remediation attempted (postmortem generated standalone)."
    action = remediation.action
    if action == "rolled_back":
        return (
            f"Autonomous rollback executed: {remediation.current_revision} -> "
            f"{remediation.target_revision}."
        )
    if action == "dry_run":
        return f"Rollback evaluated in dry-run only: {remediation.reason}"
    if action == "skipped":
        return f"Rollback skipped by guardrails: {remediation.reason}"
    if action == "error":
        return f"Rollback attempt errored: {remediation.reason}"
    return f"Remediation action: {action} ({remediation.reason})"


@dataclass
class Postmortem:
    signal: str
    title: str
    service: Optional[str]
    severity: str
    probable_causes: List[str]
    improvement_proposals: List[str]
    runbooks: List[str]
    remediation_summary: str
    generated_at: datetime.datetime = field(default_factory=_utcnow)
    generator: str = "deterministic"  # never an LLM — the failure path stays predictable

    def as_dict(self) -> dict:
        return {
            "signal": self.signal,
            "title": self.title,
            "service": self.service,
            "severity": self.severity,
            "probable_causes": list(self.probable_causes),
            "improvement_proposals": list(self.improvement_proposals),
            "runbooks": list(self.runbooks),
            "remediation_summary": self.remediation_summary,
            "generated_at": self.generated_at.isoformat(),
            "generator": self.generator,
        }


def analyze_incident(
    incident: Incident,
    remediation: Optional[RemediationResult] = None,
    now: Optional[datetime.datetime] = None,
) -> Postmortem:
    """Deterministically produce a root-cause analysis + improvement proposals for an incident.

    Pure and never raises: the failure path must always yield a usable postmortem, so any
    unclassifiable incident falls back to the ``unknown`` signal rather than erroring.
    """
    signal = classify_signal(incident)
    kb = _KB.get(signal, _KB[SIGNAL_UNKNOWN])
    return Postmortem(
        signal=signal,
        title=kb.title,
        service=incident.service,
        severity=_severity(signal, remediation),
        probable_causes=list(kb.probable_causes),
        improvement_proposals=list(kb.improvement_proposals),
        runbooks=list(kb.runbooks),
        remediation_summary=_remediation_summary(remediation),
        generated_at=now or _utcnow(),
    )


def render_markdown(pm: Postmortem) -> str:
    """Render a human-readable postmortem document (deterministic; safe to attach to an incident)."""
    lines: List[str] = []
    lines.append(f"# Incident Postmortem — {pm.title}")
    lines.append("")
    lines.append(f"- **Service**: {pm.service or 'unknown'}")
    lines.append(f"- **Signal**: {pm.signal}")
    lines.append(f"- **Severity**: {pm.severity}")
    lines.append(f"- **Generated at**: {pm.generated_at.isoformat()}")
    lines.append(f"- **Generator**: {pm.generator} (rule-based; no LLM in the failure path)")
    lines.append("")
    lines.append("## Remediation")
    lines.append(f"{pm.remediation_summary}")
    lines.append("")
    lines.append("## Probable root causes")
    for cause in pm.probable_causes:
        lines.append(f"- {cause}")
    lines.append("")
    lines.append("## Improvement proposals")
    for proposal in pm.improvement_proposals:
        lines.append(f"- {proposal}")
    lines.append("")
    lines.append("## Runbooks")
    for runbook in pm.runbooks:
        lines.append(f"- {runbook}")
    lines.append("")
    return "\n".join(lines)
