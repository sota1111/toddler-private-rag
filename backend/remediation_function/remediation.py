"""SOT-1480 (P2): autonomous runtime rollback — pure decision logic.

This is the "runtime version" of the deploy-time canary rollback in
``.github/workflows/deploy-cloudrun.yml`` (SOT-1469 B2). A Cloud Monitoring alert
(5xx / latency / LLM error, see ``infra/terraform/monitoring.tf``) fires a webhook
notification channel that hits the small remediation Cloud Run service. This module
decides — with guardrails — whether the incident is attributable to a recent deploy
and, unless in dry-run, shifts 100% of Cloud Run traffic back to the previous healthy
revision.

Design: this module is import-safe WITHOUT ``functions_framework`` or any GCP client at
import time (the GCP client imports google-auth/requests lazily inside its methods), so the
decision logic runs in the backend CI image (which installs only ``backend/requirements.txt``).
The HTTP entrypoint lives in ``main.py``.

Guardrails (see ``evaluate_guardrails`` / ``decide_and_rollback``):
  * only act on OPEN incidents that name a Cloud Run service;
  * optional service allowlist;
  * cooldown — do not roll back the same service again within a window;
  * recent-deploy attribution — only roll back when the currently-serving revision is young
    enough that a recent deploy is a plausible cause (otherwise defer to a human);
  * dry-run mode (DEFAULT ON) — compute and log the decision but never change traffic;
  * every decision is emitted as a structured ``[remediation]`` audit log line.
"""
from __future__ import annotations

import datetime
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _env_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_rfc3339(value: Optional[str]) -> Optional[datetime.datetime]:
    """Parse an RFC3339 timestamp (e.g. Cloud Run ``createTime``) to an aware datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


# --- Configuration ---------------------------------------------------------------
@dataclass
class RemediationConfig:
    project: str
    region: str
    dry_run: bool = True
    cooldown_seconds: int = 3600
    deploy_window_seconds: int = 3600
    allowed_services: Optional[frozenset] = None  # None => every service is eligible
    token: str = ""

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "RemediationConfig":
        env = env if env is not None else os.environ
        allowed = (env.get("REMEDIATION_ALLOWED_SERVICES") or "").strip()
        allowed_set = frozenset(s.strip() for s in allowed.split(",") if s.strip()) or None
        return cls(
            project=env.get("GCP_PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT") or "",
            region=env.get("GCP_REGION") or env.get("GOOGLE_CLOUD_LOCATION") or "asia-northeast1",
            # Safe by default: rollback is only *executed* when explicitly disabled.
            dry_run=_env_truthy(env.get("REMEDIATION_DRY_RUN", "true")),
            cooldown_seconds=int(env.get("REMEDIATION_COOLDOWN_SECONDS", "3600")),
            deploy_window_seconds=int(env.get("REMEDIATION_DEPLOY_WINDOW_SECONDS", "3600")),
            allowed_services=allowed_set,
            token=env.get("REMEDIATION_TOKEN", "") or "",
        )


# --- Incident parsing ------------------------------------------------------------
@dataclass
class Incident:
    state: str
    service: Optional[str]
    policy: str = ""
    condition: str = ""
    region: Optional[str] = None
    project: Optional[str] = None


def parse_incident(payload: dict) -> Incident:
    """Parse a Cloud Monitoring webhook payload into an :class:`Incident`.

    Cloud Run alert policies group by ``resource.labels.service_name``; some payloads
    carry the service under ``metric.labels`` instead, so we look in both.
    """
    inc = (payload or {}).get("incident", {}) or {}
    res_labels = (inc.get("resource", {}) or {}).get("labels", {}) or {}
    metric_labels = (inc.get("metric", {}) or {}).get("labels", {}) or {}
    service = res_labels.get("service_name") or metric_labels.get("service_name")
    return Incident(
        state=(inc.get("state") or "").strip().lower(),
        service=service,
        policy=inc.get("policy_name", "") or "",
        condition=inc.get("condition_name", "") or "",
        region=res_labels.get("location") or res_labels.get("region"),
        project=res_labels.get("project_id"),
    )


# --- Guardrails ------------------------------------------------------------------
def evaluate_guardrails(
    incident: Incident,
    cfg: RemediationConfig,
    last_rollback_at: Optional[datetime.datetime],
    now: datetime.datetime,
) -> Tuple[bool, str]:
    """Return ``(proceed, reason)``. Pure — never touches Cloud Run."""
    # An empty state is tolerated (treated as open) since some test/manual payloads omit it.
    if incident.state and incident.state != "open":
        return False, f"incident state is '{incident.state}', not 'open'"
    if not incident.service:
        return False, "no Cloud Run service_name in incident payload"
    if cfg.allowed_services is not None and incident.service not in cfg.allowed_services:
        return False, f"service '{incident.service}' is not in the allowlist"
    if last_rollback_at is not None:
        elapsed = (now - last_rollback_at).total_seconds()
        if elapsed < cfg.cooldown_seconds:
            return False, (
                f"cooldown active for '{incident.service}' "
                f"({elapsed:.0f}s < {cfg.cooldown_seconds}s)"
            )
    return True, "guardrails passed"


def pick_rollback_target(
    ready_revisions: List[Tuple[str, Optional[datetime.datetime]]],
    current: str,
) -> Optional[str]:
    """Newest ready revision that is not the currently-serving one, or ``None``."""
    for name, _created in ready_revisions:
        if name and name != current:
            return name
    return None


# --- Cloud Run client abstraction ------------------------------------------------
class CloudRunClient(Protocol):  # pragma: no cover - typing only
    def current_serving_revision(self, service: str) -> Optional[str]: ...
    def revision_create_time(
        self, service: str, revision: str
    ) -> Optional[datetime.datetime]: ...
    def list_ready_revisions(
        self, service: str
    ) -> List[Tuple[str, Optional[datetime.datetime]]]: ...
    def set_traffic(self, service: str, revision: str) -> None: ...


class CooldownStore(Protocol):  # pragma: no cover - typing only
    def get_last_rollback(self, service: str) -> Optional[datetime.datetime]: ...
    def record_rollback(self, service: str, when: datetime.datetime) -> None: ...


class InMemoryCooldownStore:
    """Process-local cooldown store (used as a fallback and in tests)."""

    def __init__(self) -> None:
        self._data: dict = {}

    def get_last_rollback(self, service: str) -> Optional[datetime.datetime]:
        return self._data.get(service)

    def record_rollback(self, service: str, when: datetime.datetime) -> None:
        self._data[service] = when


# --- Core decision ---------------------------------------------------------------
@dataclass
class RemediationResult:
    service: Optional[str]
    action: str = "none"  # none | skipped | dry_run | rolled_back | error
    reason: str = ""
    dry_run: bool = True
    current_revision: Optional[str] = None
    target_revision: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "service": self.service,
            "action": self.action,
            "reason": self.reason,
            "dry_run": self.dry_run,
            "current_revision": self.current_revision,
            "target_revision": self.target_revision,
        }


def _audit(result: RemediationResult) -> None:
    logger.info(
        "[remediation] action=%s service=%s dry_run=%s current=%s target=%s reason=%s",
        result.action,
        result.service,
        result.dry_run,
        result.current_revision,
        result.target_revision,
        result.reason,
    )


def decide_and_rollback(
    incident: Incident,
    client: CloudRunClient,
    store: CooldownStore,
    cfg: RemediationConfig,
    now: Optional[datetime.datetime] = None,
) -> RemediationResult:
    """Apply guardrails and, unless dry-run, roll traffic back to the previous revision."""
    now = now or _utcnow()
    result = RemediationResult(service=incident.service, dry_run=cfg.dry_run)

    last = store.get_last_rollback(incident.service) if incident.service else None
    proceed, reason = evaluate_guardrails(incident, cfg, last, now)
    if not proceed:
        result.action, result.reason = "skipped", reason
        _audit(result)
        return result

    try:
        current = client.current_serving_revision(incident.service)  # type: ignore[arg-type]
    except Exception as exc:  # never raise back to the alert webhook
        result.action, result.reason = "error", f"failed to read current revision: {exc}"
        _audit(result)
        return result

    if not current:
        result.action, result.reason = "skipped", "could not determine current serving revision"
        _audit(result)
        return result
    result.current_revision = current

    # Recent-deploy attribution: only auto-roll-back when the live revision is young enough
    # that a recent deploy is a plausible cause. Older revisions => defer to a human.
    created = None
    try:
        created = client.revision_create_time(incident.service, current)  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("[remediation] could not read revision create time: %s", exc)
    if created is not None:
        age = (now - created).total_seconds()
        if age > cfg.deploy_window_seconds:
            result.action = "skipped"
            result.reason = (
                f"current revision age {age:.0f}s exceeds deploy window "
                f"{cfg.deploy_window_seconds}s; incident unlikely to be deploy-caused"
            )
            _audit(result)
            return result

    try:
        ready = client.list_ready_revisions(incident.service)  # type: ignore[arg-type]
    except Exception as exc:
        result.action, result.reason = "error", f"failed to list revisions: {exc}"
        _audit(result)
        return result

    target = pick_rollback_target(ready, current)
    if not target:
        result.action = "skipped"
        result.reason = "no previous healthy revision to roll back to"
        _audit(result)
        return result
    result.target_revision = target

    if cfg.dry_run:
        result.action = "dry_run"
        result.reason = f"[dry-run] would roll back {incident.service} {current} -> {target}"
        _audit(result)
        return result

    try:
        client.set_traffic(incident.service, target)  # type: ignore[arg-type]
    except Exception as exc:
        result.action, result.reason = "error", f"failed to shift traffic: {exc}"
        _audit(result)
        return result

    store.record_rollback(incident.service, now)  # type: ignore[arg-type]
    result.action = "rolled_back"
    result.reason = f"rolled back {incident.service} {current} -> {target}"
    _audit(result)
    return result


# --- Real GCP implementations (imported lazily; not exercised in CI) --------------
class CloudRunAdminClient:
    """Cloud Run Admin API v2 client (google-auth + requests, imported lazily)."""

    _BASE = "https://run.googleapis.com/v2"

    def __init__(self, project: str, region: str) -> None:
        self.project = project
        self.region = region
        self._session = None

    def _sess(self):
        if self._session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self._session = AuthorizedSession(creds)
        return self._session

    def _service_url(self, service: str) -> str:
        return f"{self._BASE}/projects/{self.project}/locations/{self.region}/services/{service}"

    def current_serving_revision(self, service: str) -> Optional[str]:
        resp = self._sess().get(self._service_url(service), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        best, best_pct = None, -1
        for t in data.get("trafficStatuses", []) or []:
            pct = t.get("percent", 0) or 0
            rev = t.get("revision")
            if rev and pct > best_pct:
                best, best_pct = rev, pct
        if best:
            return best
        latest = data.get("latestReadyRevision", "") or ""
        return latest.split("/")[-1] or None

    def revision_create_time(self, service: str, revision: str) -> Optional[datetime.datetime]:
        resp = self._sess().get(f"{self._service_url(service)}/revisions/{revision}", timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return _parse_rfc3339(resp.json().get("createTime"))

    def list_ready_revisions(
        self, service: str
    ) -> List[Tuple[str, Optional[datetime.datetime]]]:
        resp = self._sess().get(f"{self._service_url(service)}/revisions", timeout=15)
        resp.raise_for_status()
        out: List[Tuple[str, Optional[datetime.datetime]]] = []
        for rev in resp.json().get("revisions", []) or []:
            name = (rev.get("name") or "").split("/")[-1]
            ready = any(
                c.get("type") == "Ready" and c.get("state") == "CONDITION_SUCCEEDED"
                for c in rev.get("conditions", []) or []
            )
            if name and ready:
                out.append((name, _parse_rfc3339(rev.get("createTime"))))
        out.sort(key=lambda item: (item[1] or _EPOCH), reverse=True)
        return out

    def set_traffic(self, service: str, revision: str) -> None:
        body = {
            "traffic": [
                {
                    "type": "TRAFFIC_TARGET_ALLOCATION_TYPE_REVISION",
                    "revision": revision,
                    "percent": 100,
                }
            ]
        }
        resp = self._sess().patch(
            f"{self._service_url(service)}?updateMask=traffic", json=body, timeout=30
        )
        resp.raise_for_status()


class FirestoreCooldownStore:
    """Cooldown state persisted in Firestore (shared across stateless instances)."""

    def __init__(self, project: str, collection: str = "remediation_state") -> None:
        from google.cloud import firestore

        self._db = firestore.Client(project=project or None)
        self._collection = collection

    def get_last_rollback(self, service: str) -> Optional[datetime.datetime]:
        try:
            doc = self._db.collection(self._collection).document(service).get()
            if doc.exists:
                return (doc.to_dict() or {}).get("last_rollback_at")
        except Exception as exc:  # fail-open: absence of state must not block a needed rollback
            logger.warning("[remediation] cooldown read failed for %s: %s", service, exc)
        return None

    def record_rollback(self, service: str, when: datetime.datetime) -> None:
        try:
            self._db.collection(self._collection).document(service).set(
                {"last_rollback_at": when}
            )
        except Exception as exc:
            logger.warning("[remediation] cooldown write failed for %s: %s", service, exc)
