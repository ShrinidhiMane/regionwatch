#!/usr/bin/env bash
# Inject a failure into one of the demo services.
# Usage: ./scripts/chaos.sh <service> <healthy|slow|failing|crash>
# Example: ./scripts/chaos.sh api-us-east crash
set -euo pipefail

declare -A PORTS=( [api-us-east]=8001 [api-us-west]=8002 [auth-us-east]=8003 )
svc="${1:?service name (api-us-east | api-us-west | auth-us-east)}"
mode="${2:?mode (healthy | slow | failing | crash)}"
port="${PORTS[$svc]:?unknown service $svc}"

curl -fsS -X POST "http://localhost:${port}/chaos/${mode}" && echo
