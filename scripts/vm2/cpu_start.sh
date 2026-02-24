#!/bin/bash
# Start CPU stress for chaos testing (e.g. stress-ng)
set -e
stress-ng --cpu 2 --timeout 60s &
echo "CPU stress started (PID $!)"
