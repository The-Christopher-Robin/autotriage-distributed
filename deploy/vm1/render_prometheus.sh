#!/usr/bin/env bash
# Render prometheus.yml from prometheus.yml.tmpl using VM2_IP from environment.
# Run from deploy/vm1 after copying .env.example to .env (or export VM2_IP).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
[ -f .env ] && set -a && source .env && set +a
if [ -z "${VM2_IP}" ]; then
  echo "ERROR: VM2_IP not set. Source .env or export VM2_IP." >&2
  exit 1
fi
envsubst '${VM2_IP}' < prometheus.yml.tmpl > prometheus.yml
echo "Rendered prometheus.yml with VM2_IP=${VM2_IP}"
