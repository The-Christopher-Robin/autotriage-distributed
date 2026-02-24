#!/bin/bash
# Stop CPU stress
pkill -f stress-ng || true
echo "CPU stress stopped"
