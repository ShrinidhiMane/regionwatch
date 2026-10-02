#!/bin/sh
# Hosted demo: three demo services on localhost, then the monitor on $PORT (set by the host).
set -e
cd /app/demo_service
SERVICE_NAME=api  REGION=us-east-sim uvicorn app:app --host 127.0.0.1 --port 8001 --log-level warning &
SERVICE_NAME=api  REGION=us-west-sim uvicorn app:app --host 127.0.0.1 --port 8002 --log-level warning &
SERVICE_NAME=auth REGION=us-east-sim uvicorn app:app --host 127.0.0.1 --port 8003 --log-level warning &
cd /app
exec python -m regionwatch --config config/targets.demo.yaml --port "${PORT:-8080}"
