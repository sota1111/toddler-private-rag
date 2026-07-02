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
    return _json(result.as_dict(), 200)
