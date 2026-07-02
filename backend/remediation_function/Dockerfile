# SOT-1480: Cloud Run service for autonomous runtime rollback (remediation).
# Slim, self-contained (does NOT import backend/app). Triggered by the Cloud Monitoring
# remediation webhook notification channel; shifts Cloud Run traffic back to the previous
# healthy revision when an incident is attributable to a recent deploy (guardrails in
# remediation.py: token auth, dry-run default-on, cooldown, deploy-window attribution).
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
# functions-framework provides a production WSGI server (gunicorn) for Cloud Run.
CMD exec functions-framework --target=remediate --source=main.py --port=$PORT
