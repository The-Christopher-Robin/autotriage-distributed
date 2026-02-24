#!/bin/bash
# Restart a service container (remediation)
# Usage: ./restart.sh <container_name>
CONTAINER="${1:-payments}"
docker restart "$CONTAINER"
echo "Restarted: $CONTAINER"
