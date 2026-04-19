"""Feed realistic fake robot telemetry into the Quest integration pipeline.

This script is intended for hardware-less testing when the real robot arm is
offline. It can drive two existing paths in this repo:

1) Voice bridge WebSocket (`scripts/voice_bridge/voice_bridge_server.py`)
   - Starts a bridge server in-process.
   - Publishes LeRobot-style joint keys to `latest_joint_state_store`.

2) Browser digital twin HTTP endpoint (`meta-quest-camera-feed/server.py`)
   - Optionally POSTs converted state to `/robot_state`.

Usage examples:

    # WebSocket joint-state stream only (Quest voice app)
    python scripts/voice_bridge/fake_robot_state_feeder.py \
        --host 0.0.0.0 --port 8765 --hz 30

    # Also mirror state to the browser twin endpoint
    python scripts/voice_bridge/fake_robot_state_feeder.py \
        --host 0.0.0.0 --port 8765 --hz 30 \
        --http-server http://127.0.0.1:5000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import random
import threading
import time
import urllib.error
import urllib.request

from voice_bridge_server import latest_command_store, latest_joint_state_store, serve


log = logging.getLogger("fake_robot_feed")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _post_json(url: str, payload: dict, timeout: float) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _start_bridge_thread(host: str, port: int) -> threading.Thread:
    def _run() -> None:
        asyncio.run(serve(host, port, latest_command_store, latest_joint_state_store))

    thread = threading.Thread(target=_run, name="voice-bridge", daemon=True)
    thread.start()
    return thread


def _fake_observation(t: float, noise: dict[str, float], rng: random.Random) -> dict[str, float]:
    """Generate smooth, bounded, robot-like joint trajectories.

    Values are in degrees for rotational joints, matching common LeRobot
    telemetry conventions for `.pos` fields.
    """

    base = {
        "shoulder_pan.pos": 12.0 * math.sin(2.0 * math.pi * 0.11 * t),
        "shoulder_lift.pos": 22.0 + 18.0 * math.sin(2.0 * math.pi * 0.09 * t + 0.9),
        "elbow_flex.pos": -38.0 + 28.0 * math.sin(2.0 * math.pi * 0.09 * t + 2.0),
        "wrist_flex.pos": 16.0 * math.sin(2.0 * math.pi * 0.16 * t + 1.1),
        "wrist_roll.pos": 35.0 * math.sin(2.0 * math.pi * 0.05 * t + 0.7),
        "gripper.pos": 5.0 + 4.0 * (0.5 + 0.5 * math.sin(2.0 * math.pi * 0.33 * t + 0.2)),
    }

    # Add low-frequency, low-amplitude sensor-like drift so motion is not too
    # perfectly sinusoidal.
    for key, value in list(base.items()):
        prev = noise.get(key, 0.0)
        drift = 0.92 * prev + 0.08 * rng.gauss(0.0, 0.5)
        noise[key] = drift
        base[key] = value + drift

    # Keep values in practical ranges for visualizers.
    base["shoulder_pan.pos"] = _clamp(base["shoulder_pan.pos"], -90.0, 90.0)
    base["shoulder_lift.pos"] = _clamp(base["shoulder_lift.pos"], -60.0, 70.0)
    base["elbow_flex.pos"] = _clamp(base["elbow_flex.pos"], -120.0, 90.0)
    base["wrist_flex.pos"] = _clamp(base["wrist_flex.pos"], -90.0, 90.0)
    base["wrist_roll.pos"] = _clamp(base["wrist_roll.pos"], -180.0, 180.0)
    base["gripper.pos"] = _clamp(base["gripper.pos"], 0.0, 12.0)
    return base


def _to_http_robot_state(positions: dict[str, float], t: float) -> dict:
    # Gentle base sway and moving end-effector target for easier visual QA.
    base_x = 0.03 * math.sin(2.0 * math.pi * 0.04 * t)
    base_z = -1.4 + 0.02 * math.cos(2.0 * math.pi * 0.03 * t)
    target_x = 0.28 + 0.08 * math.cos(2.0 * math.pi * 0.07 * t)
    target_y = 1.24 + 0.06 * math.sin(2.0 * math.pi * 0.11 * t)
    target_z = -1.05 + 0.10 * math.sin(2.0 * math.pi * 0.07 * t)

    # Map richer robot state onto the simpler browser twin schema.
    gripper_gap = 0.02 + 0.06 * (positions["gripper.pos"] / 12.0)
    return {
        "basePosition": {"x": base_x, "y": 1.15, "z": base_z},
        "baseRotation": {"x": 0.0, "y": 180.0, "z": 0.0},
        "joints": {
            "shoulder": positions["shoulder_lift.pos"],
            "elbow": positions["elbow_flex.pos"],
            "wrist": positions["wrist_flex.pos"],
            "wristRotate": positions["wrist_roll.pos"],
            "gripper": _clamp(gripper_gap, 0.0, 0.12),
        },
        "target": {"x": target_x, "y": target_y, "z": target_z},
        "timestamp": time.time(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fake robot telemetry feeder for Quest testing")
    parser.add_argument("--host", default="0.0.0.0", help="Voice bridge bind address")
    parser.add_argument("--port", type=int, default=8765, help="Voice bridge bind port")
    parser.add_argument("--hz", type=float, default=30.0, help="Telemetry publish rate")
    parser.add_argument(
        "--http-server",
        default=None,
        help="Optional base URL for meta-quest-camera-feed (e.g. http://127.0.0.1:5000)",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=0.75,
        help="HTTP POST timeout in seconds when --http-server is enabled",
    )
    parser.add_argument("--seed", type=int, default=7, help="Random seed for deterministic playback")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    _start_bridge_thread(args.host, args.port)
    log.info("Voice bridge started at ws://%s:%d", args.host, args.port)

    http_url = None
    if args.http_server:
        http_url = args.http_server.rstrip("/") + "/robot_state"
        log.info("HTTP mirror enabled -> %s", http_url)

    hz = max(1.0, args.hz)
    interval = 1.0 / hz
    rng = random.Random(args.seed)
    noise: dict[str, float] = {}
    started = time.monotonic()
    last_http_error_at = 0.0

    log.info("Publishing fake telemetry at %.1f Hz", hz)
    try:
        while True:
            loop_start = time.monotonic()
            t = loop_start - started

            positions = _fake_observation(t, noise, rng)
            latest_joint_state_store.update(positions, ts=time.time())

            if http_url is not None:
                payload = _to_http_robot_state(positions, t)
                try:
                    _post_json(http_url, payload, timeout=args.http_timeout)
                except urllib.error.URLError as exc:
                    # Throttle repeated connection errors to keep logs readable.
                    now = time.monotonic()
                    if now - last_http_error_at > 2.0:
                        log.warning("HTTP mirror post failed: %s", exc)
                        last_http_error_at = now

            elapsed = time.monotonic() - loop_start
            sleep_for = interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        log.info("Stopping fake telemetry feeder")


if __name__ == "__main__":
    main()