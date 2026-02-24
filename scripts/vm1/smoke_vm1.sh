#!/usr/bin/env bash
# Smoke check for VM1 (node-a): gateway /health and /checkout.
# Usage: ./smoke_vm1.sh [base_url]
# Example: ./smoke_vm1.sh http://192.168.56.101:8000
set -e
BASE="${1:-http://localhost:8000}"
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

echo "Smoke check VM1 (gateway) at $BASE"
check "gateway /health" "$BASE/health"
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/checkout" -H "Content-Type: application/json" -d '{}' 2>/dev/null || echo "000")
if [ "$code" = "200" ] || [ "$code" = "502" ] || [ "$code" = "504" ]; then
  echo "OK gateway /checkout (POST) -> $code"
else
  echo "FAIL gateway /checkout (POST) -> $code"
  FAIL=1
fi

if [ $FAIL -eq 0 ]; then
  echo "Smoke VM1: success"
  exit 0
else
  echo "Smoke VM1: one or more checks failed"
  exit 1
fi
