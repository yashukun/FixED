#!/usr/bin/env bash
# Smoke-test the deployed stack: every service's /health through the ALB ingress.
# Required env: BASE_URL  (e.g. https://api.example.com or http://<alb-dns-name>)
set -euo pipefail
: "${BASE_URL:?}"

fail=0
for svc in gateway ingest search qpaper viva; do
  url="${BASE_URL%/}/api/${svc}/health"
  code=$(curl -ksSL -o /dev/null -w '%{http_code}' --max-time 15 "$url" || echo 000)
  echo "${url} -> ${code}"
  [ "$code" = "200" ] || fail=1
done

if [ "$fail" != "0" ]; then
  echo "::error::Smoke test failed"
  exit 1
fi
echo "Smoke test passed."
