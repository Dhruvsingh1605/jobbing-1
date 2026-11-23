#!/bin/bash
# 00:30 IST nightly: delete the day's logs/screenshots (dedupe DB is kept).
cd /root/jobbing/job-agent || exit 1
export TZ=Asia/Kolkata
./.venv/bin/python -m agent cleanup
