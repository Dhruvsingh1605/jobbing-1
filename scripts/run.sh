#!/bin/bash
# Cron entrypoint. Usage: run.sh [extra args for `agent run`]
cd /root/jobbing/job-agent || exit 1
export TZ=Asia/Kolkata
exec /usr/bin/flock -n /root/jobbing/job-agent/data/.cron.lock \
  ./.venv/bin/python -m agent run "$@" >> logs/cron.out 2>&1
