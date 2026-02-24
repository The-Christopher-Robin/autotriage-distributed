#!/usr/bin/env bash
# Smoke check for VM2 (node-b): orders /health and payments /health.
# Usage: ./smoke_vm2.sh [orders_base] [payments_base]
# Example: ./smoke_vm2.sh http://localhost:8000 http://localhost:8001
set -e
ORDERS_BASE="${1:-http://localhost:8000}"
PAYMENTS_BASE="${2:-http://localhost:8001}"
FAIL=0

check() {
  local name="$1"
  local url="$2"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then
    echo "OK $name ($url) -> $code"
  else
    echo "FAIL $name ($url) -> $code"
    FAIL=1
  fi
}

echo "Smoke check VM2 (orders, payments)"
check "orders /health" "$ORDERS_BASE/health"
check "payments /health" "$PAYMENTS_BASE/health"

if [ $FAIL -eq 0 ]; then
  echo "Smoke VM2: success"
  exit 0
else
  echo "Smoke VM2: one or more checks failed"
  exit 1
fi
