#!/bin/bash
# Run experiment sequence: baseline, inject chaos (VM2), observe, clear
set -e
GATEWAY="${GATEWAY_URL:-http://localhost:8000}"
echo "=== Baseline (30s) ==="
./loadgen.sh "$GATEWAY" 30
echo "=== Inject chaos on VM2 (run netem_apply.sh or crash.sh there), then load (60s) ==="
read -p "Press Enter after injecting chaos..."
./loadgen.sh "$GATEWAY" 60
echo "=== Clear chaos on VM2 (netem_clear.sh / restart.sh), then load (30s) ==="
read -p "Press Enter after clearing..."
./loadgen.sh "$GATEWAY" 30
echo "Done."
