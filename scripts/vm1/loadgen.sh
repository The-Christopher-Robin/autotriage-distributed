#!/bin/bash
# Load generator: hit /checkout on gateway
# Usage: ./loadgen.sh [gateway_url] [duration_sec] [-c parallelism]
#
# Examples:
#   ./loadgen.sh http://localhost:8000 60          # sequential (default)
#   ./loadgen.sh http://localhost:8000 60 -c 8     # 8 concurrent workers

GATEWAY="${1:-http://localhost:8000}"
DURATION="${2:-60}"
MODE="sequential"
PARALLELISM=1
COUNT=0

# Parse optional flags
shift 2 2>/dev/null
while [ $# -gt 0 ]; do
  case "$1" in
    -c|--concurrent)
      MODE="concurrent"
      PARALLELISM="${2:-8}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

_worker() {
  local id=$1
  local end=$((SECONDS + DURATION))
  local n=0
  while [ $SECONDS -lt $end ]; do
    code=$(curl -s -X POST "$GATEWAY/checkout" \
      -H "Content-Type: application/json" -d '{}' \
      -o /dev/null -w "%{http_code}" --max-time 10 2>/dev/null)
    n=$((n + 1))
  done
  echo "$n"
}

if [ "$MODE" = "concurrent" ]; then
  echo "Load gen (concurrent): $GATEWAY/checkout for ${DURATION}s with $PARALLELISM workers"
  START_TIME=$SECONDS
  pids=()
  tmpdir=$(mktemp -d)
  for i in $(seq 1 "$PARALLELISM"); do
    _worker "$i" > "$tmpdir/w$i" &
    pids+=($!)
  done

  total=0
  for pid in "${pids[@]}"; do
    wait "$pid"
  done
  for i in $(seq 1 "$PARALLELISM"); do
    n=$(cat "$tmpdir/w$i" 2>/dev/null || echo 0)
    total=$((total + n))
  done
  elapsed=$((SECONDS - START_TIME))
  rm -rf "$tmpdir"
  echo "Done: $total requests in ${elapsed}s (~$((total / (elapsed > 0 ? elapsed : 1))) req/s) with $PARALLELISM workers"
else
  echo "Load gen (sequential): $GATEWAY/checkout for ${DURATION}s"
  START_TIME=$SECONDS
  end=$((SECONDS + DURATION))
  while [ $SECONDS -lt $end ]; do
    curl -s -X POST "$GATEWAY/checkout" \
      -H "Content-Type: application/json" -d '{}' \
      -o /dev/null -w "%{http_code}\n" --max-time 10 2>/dev/null
    COUNT=$((COUNT + 1))
  done
  elapsed=$((SECONDS - START_TIME))
  echo "Done: $COUNT requests in ${elapsed}s"
fi
