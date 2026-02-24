#!/bin/bash
# Remove netem rules
set -e
IFACE="${IFACE:-eth0}"
sudo tc qdisc del dev "$IFACE" root 2>/dev/null || true
echo "Cleared netem on $IFACE"
