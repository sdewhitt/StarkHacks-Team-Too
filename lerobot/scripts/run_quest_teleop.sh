#!/usr/bin/env bash
set -euo pipefail

record=0
episodes=1
stream_url=""
repo_id=""

usage() {
  cat <<'EOF'
Usage: run_quest_teleop.sh [--record] [--episodes N] [--stream-url URL] [--repo-id ORG/NAME]

  --record           Run lerobot-record instead of lerobot-teleoperate
  --episodes N       Number of episodes to record (used with --record)
  --stream-url URL   MJPEG stream URL for the Quest wrist camera
  --repo-id ORG/NAME Dataset repo id (required with --record)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --record)
      record=1
      shift
      ;;
    --episodes)
      episodes="${2:?Missing value for --episodes}"
      shift 2
      ;;
    --stream-url)
      stream_url="${2:?Missing value for --stream-url}"
      shift 2
      ;;
    --repo-id)
      repo_id="${2:?Missing value for --repo-id}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "$repo_root"

read -r SO101_PORT QUEST_CALIB_DIR QUEST_ID ROBOT_CALIB_DIR ROBOT_ID < <(uv run python - <<'PY'
from pathlib import Path
import re

from lerobot.utils.constants import HF_LEROBOT_CALIBRATION, ROBOTS, TELEOPERATORS
from lerobot.scripts.lerobot_find_port import find_available_ports

def latest_json_id(directory: Path, default_id: str) -> tuple[str, str]:
    if not directory.exists():
        return str(directory), default_id
    json_files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        return str(directory), default_id
    return str(directory), json_files[0].stem

ports = find_available_ports()
preferred_patterns = [r"usbmodem", r"usbserial", r"ttyACM", r"ttyUSB"]
selected = None
for pattern in preferred_patterns:
    matched = [p for p in ports if re.search(pattern, p, re.IGNORECASE)]
    if len(matched) == 1:
        selected = matched[0]
        break
    if len(matched) > 1:
        selected = matched[0]
        break
if selected is None:
    if len(ports) == 1:
        selected = ports[0]
    else:
        raise SystemExit(f"Could not auto-detect a unique SO-101 port from: {ports}")

quest_dir, quest_id = latest_json_id(HF_LEROBOT_CALIBRATION / TELEOPERATORS / "quest", "quest")
robot_dir, robot_id = latest_json_id(HF_LEROBOT_CALIBRATION / ROBOTS / "so101_follower", "so101_follower")
print(selected, quest_dir, quest_id, robot_dir, robot_id)
PY
)

cmd=(uv run)
if [[ "$record" -eq 1 ]]; then
  if [[ -z "$repo_id" ]]; then
    echo "--repo-id is required when using --record" >&2
    exit 1
  fi
  cmd+=(lerobot-record)
else
  cmd+=(lerobot-teleoperate)
fi

cmd+=(
  --robot.type=so101_follower
  --robot.port="$SO101_PORT"
  --robot.id="$ROBOT_ID"
  --robot.calibration_dir="$ROBOT_CALIB_DIR"
  --teleop.type=quest_teleop
  --teleop.calibration_dir="$QUEST_CALIB_DIR"
  --teleop.id="$QUEST_ID"
)

if [[ -n "$stream_url" ]]; then
  cmd+=(
    --robot.cameras="{wrist: {type: mjpeg_stream, url: \"$stream_url\", width: 640, height: 480, fps: 30, name: wrist}}"
  )
fi

if [[ "$record" -eq 1 ]]; then
  cmd+=(
    --dataset.repo_id="$repo_id"
    --dataset.num_episodes="$episodes"
    --dataset.single_task="Quest teleoperation"
  )
fi

exec "${cmd[@]}"


