#!/bin/bash
# Installs the 4x/day schedule + nightly cleanup. Times are IST, converted to UTC because this VPS runs in UTC
# (IST = UTC+5:30, no DST):  06:00 IST=00:30 UTC | 11:00=05:30 | 15:00=09:30 | 18:00=12:30 | cleanup 00:30 IST=19:00 UTC
set -e
D=/root/jobbing/job-agent
( { crontab -l 2>/dev/null | grep -v "job-agent"; true; } ; cat <<CRON
# job-agent (Dhruv) - all times shown in IST
30 0  * * * $D/scripts/run.sh   # 06:00 IST
30 5  * * * $D/scripts/run.sh   # 11:00 IST
30 9  * * * $D/scripts/run.sh   # 15:00 IST
30 12 * * * $D/scripts/run.sh   # 18:00 IST
0  19 * * * $D/scripts/cleanup.sh   # 00:30 IST - wipe logs
CRON
) | crontab -
crontab -l | grep job-agent -A5
