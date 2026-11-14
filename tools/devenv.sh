#!/usr/bin/env bash
# Development only: a DSH test profile for real-model runs in the cloud container.
#
#   tools/devenv.sh <work-dir> [minutes]   # set up (idempotent), then print the launch command
#
# Needs the cloud environment's setup script (DSH 0.2.2-rc.2 in /opt/lh/dsh, a
# venv with pygame-ce + zstandard in /opt/lh/venv). The DeepSeek key is injected
# by the proxy, so DEEPSEEK_API_KEY is only a placeholder. With minutes > 0 the
# plugin opens a temporary free time 5 s after DSH starts; 0 = the real schedule.
set -e
W=$(mkdir -p "${1:?work dir}" && cd "$1" && pwd)
MIN=${2:-10}
REPO=$(cd "$(dirname "$0")/.." && pwd)
LH=${LH_OPT:-/opt/lh}
export DSH_HOME=$W/dsh-home DEEPSEEK_API_KEY=proxy-injected
if [ ! -d "$DSH_HOME/profiles/lhtest" ]; then
  (cd "$LH/dsh" && npx dsh --profile lhtest --from-default-profile web --dump-config >/dev/null)
fi
python3 "$REPO/scripts/install.py" --profile lhtest >/dev/null
DELAY=$([ "$MIN" -gt 0 ] && echo 5 || echo 0)
cat > "$W/overlay.yml" <<YML
- id: little-house
  config:
    stateDir: $W/lh-state
    house:
      python: $LH/venv/bin/python
    wake:
      firstWakeDelaySeconds: $DELAY
      testMinutes: $([ "$MIN" -gt 0 ] && echo "$MIN" || echo 40)
YML
echo "cd $LH/dsh && DSH_HOME=$DSH_HOME DEEPSEEK_API_KEY=proxy-injected npx dsh --profile lhtest --patch $W/overlay.yml --no-open --port 3099"
echo "# done when $W/lh-state/plugin.log says 'over in session'"
