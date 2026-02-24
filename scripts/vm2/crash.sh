#!/bin/bash
# Crash a service container for chaos testing
# Usage: ./crash.sh <container_name>
CONTAINER="${1:-payments}"
docker kill "$CONTAINER" 2>/dev/null || true
echo "Killed container: $CONTAINER"
