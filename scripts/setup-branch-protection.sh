#!/usr/bin/env bash
#
# SOT-1469 A1: enforce that `main` can only advance through green CI.
#
# GitHub branch protection is repository configuration, not code, so it cannot be
# committed. This script applies the intended protection via the GitHub API so the
# policy is reproducible and reviewable. Run it once (and after changing CI job
# names) with a token that has admin rights on the repo.
#
# Usage:
#   scripts/setup-branch-protection.sh [owner/repo] [branch]
# Defaults: owner/repo = sota1111/toddler-private-rag, branch = main
#
# Requires: gh CLI authenticated with admin:repo scope.
set -euo pipefail

REPO="${1:-sota1111/toddler-private-rag}"
BRANCH="${2:-main}"

# Required status checks must match the CI job names in .github/workflows/ci.yml.
# The evaluation-gate job (SOT-1469 B1) is included so accuracy regressions block
# merges to main, and the Deploy workflow (gated on CI success) never runs on red.
read -r -d '' PAYLOAD <<'JSON' || true
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["backend-tests", "evaluation-gate", "frontend-checks"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON

echo "Applying branch protection to ${REPO}@${BRANCH} ..."
echo "$PAYLOAD" | gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/${REPO}/branches/${BRANCH}/protection" \
  --input -

echo "Branch protection applied. Required checks: backend-tests, evaluation-gate, frontend-checks."
