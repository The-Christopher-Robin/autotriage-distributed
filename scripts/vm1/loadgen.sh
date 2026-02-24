#!/bin/bash
# Load generator: hit /checkout on gateway
# Usage: ./loadgen.sh [gateway_url] [duration_sec]
GATEWAY="${1:-http://localhost:8000}"
DURATION="${2:-60}"
echo "Load gen: $GATEWAY/checkout for ${DURATION}s"
end=$((SECONDS + DURATION))
while [ $SECONDS -lt $end ]; do
  curl -s -X POST "$GATEWAY/checkout" -H "Content-Type: application/json" -d '{}' -o /dev/null -w "%{http_code}\n"
done
