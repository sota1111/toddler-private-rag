"""SOT-1480 (P2): autonomous runtime rollback — functions-framework HTTP entrypoint.

Receives the Cloud Monitoring alert webhook (a POST from the ``remediation_webhook``
notification channel, see ``infra/terraform/remediation.tf``), authenticates it via the
``?token=`` query param, and hands the incident to the pure decision logic in
``remediation.py``. Deployed as a slim Cloud Run service (Dockerfile) that does NOT import
``backend/app``.
"""
import hmac
import logging

import functions_framework
from flask import Response, jsonify

import postmortem as PM
import remediation as R

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _json(payload: dict, status: int) -> Response:
    resp = jsonify(payload)
    resp.status_code = status
    return resp


@functions_framework.http
def remediate(req):
    """HTTP entry point. ``req`` is the Flask request injected by functions-framework."""
    cfg = R.RemediationConfig.from_env()

    # Fail-closed auth: the webhook MUST present the shared token. If no token is configured,
    # the service refuses to act (prevents an unauthenticated caller from triggering rollbacks).
    token = req.args.get("token", "")
    if not cfg.token or not hmac.compare_digest(token, cfg.token):
        return _json({"detail": "forbidden"}, 403)

    if req.method != "POST":
        return _json({"detail": "method not allowed"}, 405)

    payload = req.get_json(silent=True) or {}
    incident = R.parse_incident(payload)

    region = incident.region or cfg.region
    project = incident.project or cfg.project

    client = R.CloudRunAdminClient(project, region)
    store: R.CooldownStore
    if project:
        try:
            store = R.FirestoreCooldownStore(project)
        except Exception as exc:  # Firestore unavailable -> degrade to in-memory cooldown
            logger.warning("[remediation] Firestore cooldown unavailable, using in-memory: %s", exc)
            store = R.InMemoryCooldownStore()
    else:
        store = R.InMemoryCooldownStore()

    result = R.decide_and_rollback(incident, client, store, cfg)

    # SOT-1484 follow-up: deterministically analyse the incident (root cause + improvement
    # proposals) and emit it alongside the rollback decision. Rule-based, so no generative step
    # is added to the failure path. Never let postmortem generation break the webhook response.
    postmortem_dict = None
    try:
        pm = PM.analyze_incident(incident, result)
        postmortem_dict = pm.as_dict()
        logger.info(
            "[postmortem] signal=%s severity=%s service=%s causes=%d proposals=%d",
            pm.signal,
            pm.severity,
            pm.service,
            len(pm.probable_causes),
            len(pm.improvement_proposals),
        )
    except Exception as exc:  # pragma: no cover - defensive; analyze_incident is pure/never-raises
        logger.warning("[postmortem] generation failed: %s", exc)

    body = result.as_dict()
    body["postmortem"] = postmortem_dict
    return _json(body, 200)
