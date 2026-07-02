"""SOT-1480 (P2): tests for the autonomous runtime rollback decision logic.

These exercise the PURE logic in ``backend/remediation_function/remediation.py`` (guardrails,
attribution window, cooldown, dry-run, traffic shift). They inject a fake Cloud Run client and an
in-memory cooldown store, so they need no GCP access and run in the backend CI image (which does
NOT install functions_framework — the HTTP wrapper in main.py is not imported here).
"""
import datetime
import os
import sys

_REMEDIATION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "remediation_function"
)
if _REMEDIATION_DIR not in sys.path:
    sys.path.insert(0, _REMEDIATION_DIR)

import remediation as R  # noqa: E402

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)


def _incident(service="toddler-private-rag-backend", state="open", region="asia-northeast1"):
    return R.Incident(state=state, service=service, policy="5xx", region=region)


def _cfg(**kw):
    base = dict(project="proj", region="asia-northeast1", dry_run=False, token="tok")
    base.update(kw)
    return R.RemediationConfig(**base)


class FakeClient:
    def __init__(self, current, revisions, create_times=None):
        self.current = current
        self.revisions = revisions  # [(name, create_time)] newest-first
        self.create_times = create_times or {}
        self.set_calls = []

    def current_serving_revision(self, service):
        return self.current

    def revision_create_time(self, service, revision):
        return self.create_times.get(revision)

    def list_ready_revisions(self, service):
        return list(self.revisions)

    def set_traffic(self, service, revision):
        self.set_calls.append((service, revision))


# --- config / parsing ------------------------------------------------------------
def test_config_from_env_defaults_dry_run_on():
    cfg = R.RemediationConfig.from_env({})
    assert cfg.dry_run is True
    assert cfg.cooldown_seconds == 3600
    assert cfg.allowed_services is None


def test_config_from_env_reads_values():
    cfg = R.RemediationConfig.from_env(
        {
            "GCP_PROJECT_ID": "p",
            "GCP_REGION": "r",
            "REMEDIATION_DRY_RUN": "false",
            "REMEDIATION_COOLDOWN_SECONDS": "60",
            "REMEDIATION_ALLOWED_SERVICES": "a, b",
            "REMEDIATION_TOKEN": "t",
        }
    )
    assert cfg.project == "p" and cfg.region == "r"
    assert cfg.dry_run is False
    assert cfg.cooldown_seconds == 60
    assert cfg.allowed_services == frozenset({"a", "b"})
    assert cfg.token == "t"


def test_parse_incident_resource_labels():
    inc = R.parse_incident(
        {
            "incident": {
                "state": "OPEN",
                "policy_name": "5xx",
                "resource": {"labels": {"service_name": "svc", "location": "asia-northeast1"}},
            }
        }
    )
    assert inc.state == "open"
    assert inc.service == "svc"
    assert inc.region == "asia-northeast1"


def test_parse_incident_metric_labels_fallback():
    inc = R.parse_incident({"incident": {"metric": {"labels": {"service_name": "svc2"}}}})
    assert inc.service == "svc2"


# --- guardrails ------------------------------------------------------------------
def test_guardrails_skip_closed_incident():
    ok, reason = R.evaluate_guardrails(_incident(state="closed"), _cfg(), None, NOW)
    assert ok is False and "not 'open'" in reason


def test_guardrails_skip_missing_service():
    ok, reason = R.evaluate_guardrails(_incident(service=None), _cfg(), None, NOW)
    assert ok is False and "service_name" in reason


def test_guardrails_skip_not_allowlisted():
    cfg = _cfg(allowed_services=frozenset({"other"}))
    ok, reason = R.evaluate_guardrails(_incident(service="svc"), cfg, None, NOW)
    assert ok is False and "allowlist" in reason


def test_guardrails_skip_cooldown_active():
    last = NOW - datetime.timedelta(seconds=100)
    cfg = _cfg(cooldown_seconds=3600)
    ok, reason = R.evaluate_guardrails(_incident(), cfg, last, NOW)
    assert ok is False and "cooldown" in reason


def test_guardrails_pass():
    ok, reason = R.evaluate_guardrails(_incident(), _cfg(), None, NOW)
    assert ok is True


# --- target selection ------------------------------------------------------------
def test_pick_rollback_target_newest_non_current():
    revs = [("rev-3", None), ("rev-2", None), ("rev-1", None)]
    assert R.pick_rollback_target(revs, "rev-3") == "rev-2"


def test_pick_rollback_target_none_when_only_current():
    assert R.pick_rollback_target([("rev-1", None)], "rev-1") is None


# --- decide_and_rollback ---------------------------------------------------------
def test_decide_dry_run_does_not_shift_traffic():
    client = FakeClient(current="rev-2", revisions=[("rev-2", NOW), ("rev-1", NOW)])
    store = R.InMemoryCooldownStore()
    res = R.decide_and_rollback(_incident(), client, store, _cfg(dry_run=True), now=NOW)
    assert res.action == "dry_run"
    assert res.target_revision == "rev-1"
    assert client.set_calls == []
    assert store.get_last_rollback("toddler-private-rag-backend") is None


def test_decide_executes_rollback_and_records_cooldown():
    client = FakeClient(current="rev-2", revisions=[("rev-2", NOW), ("rev-1", NOW)])
    store = R.InMemoryCooldownStore()
    res = R.decide_and_rollback(_incident(), client, store, _cfg(dry_run=False), now=NOW)
    assert res.action == "rolled_back"
    assert client.set_calls == [("toddler-private-rag-backend", "rev-1")]
    assert store.get_last_rollback("toddler-private-rag-backend") == NOW


def test_decide_skips_when_revision_older_than_deploy_window():
    old = NOW - datetime.timedelta(seconds=7200)
    client = FakeClient(
        current="rev-2",
        revisions=[("rev-2", old), ("rev-1", old)],
        create_times={"rev-2": old},
    )
    res = R.decide_and_rollback(
        _incident(), client, R.InMemoryCooldownStore(), _cfg(deploy_window_seconds=3600), now=NOW
    )
    assert res.action == "skipped"
    assert "deploy window" in res.reason
    assert client.set_calls == []


def test_decide_skips_when_no_previous_revision():
    client = FakeClient(current="rev-1", revisions=[("rev-1", NOW)])
    res = R.decide_and_rollback(_incident(), client, R.InMemoryCooldownStore(), _cfg(), now=NOW)
    assert res.action == "skipped"
    assert "no previous healthy revision" in res.reason


def test_decide_skips_on_cooldown():
    client = FakeClient(current="rev-2", revisions=[("rev-2", NOW), ("rev-1", NOW)])
    store = R.InMemoryCooldownStore()
    store.record_rollback("toddler-private-rag-backend", NOW - datetime.timedelta(seconds=10))
    res = R.decide_and_rollback(_incident(), client, store, _cfg(cooldown_seconds=3600), now=NOW)
    assert res.action == "skipped"
    assert "cooldown" in res.reason
    assert client.set_calls == []


def test_decide_error_when_client_raises():
    class Boom(FakeClient):
        def current_serving_revision(self, service):
            raise RuntimeError("boom")

    client = Boom(current="x", revisions=[])
    res = R.decide_and_rollback(_incident(), client, R.InMemoryCooldownStore(), _cfg(), now=NOW)
    assert res.action == "error"
    assert "boom" in res.reason


def test_parse_rfc3339_handles_z_suffix():
    dt = R._parse_rfc3339("2026-07-02T12:00:00Z")
    assert dt == datetime.datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)
