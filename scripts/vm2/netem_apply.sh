#!/bin/bash
# Apply network delay/loss (netem) for chaos testing
# Usage: ./netem_apply.sh <delay_ms> [loss_percent]
set -e
IFACE="${IFACE:-eth0}"
DELAY="${1:-100}"
LOSS="${2:-0}"
sudo tc qdisc add dev "$IFACE" root netem delay "${DELAY}ms" loss "${LOSS}%"
echo "Applied: delay ${DELAY}ms, loss ${LOSS}% on $IFACE"
