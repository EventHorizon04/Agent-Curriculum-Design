#!/bin/sh
set -e
alembic -x url="${POSTGRES_DSN:?POSTGRES_DSN is not set}" upgrade head
exec python -m curriculum_agent.api
