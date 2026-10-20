#!/bin/sh
set -e
alembic -x url="$POSTGRES_DSN" upgrade head
exec python -m curriculum_agent.api
