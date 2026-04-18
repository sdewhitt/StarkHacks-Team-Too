"""Run SmolVLA inference with voice-driven task prompts.

Starts the voice bridge in a background thread and, each time a new transcript
arrives, uses it as the `task` prompt for SmolVLA's next action prediction.

Optionally, if ``--robot-type`` is provided, a second background thread polls
the robot's live joint positions via ``robot.get_observation()`` and publishes
them through the voice bridge so that subscribed clients (e.g. the Unity Quest
app) can read live joint state over the same WebSocket.

This is a reference loop scaffold - wire in your real camera + proprio reads
(marked with `TODO`) to actually drive your robot arm. The SmolVLA policy is
instantiated exactly as in `smolvla_base/README.md`.

Usage:
    # Voice bridge + SmolVLA, no joint streaming
    python scripts/voice_bridge/run_smolvla_voice.py \
        --model-id lerobot/smolvla_base \
        --host 0.0.0.0 --port 8765

    # Voice bridge + live joint-state streaming (SO-100 follower), dry-run
    python scripts/voice_bridge/run_smolvla_voice.py \
        --dry-run \
        --robot-type so100_follower \
        --robot-port /dev/tty.usbmodemXXXX \
        --robot-id my_arm \
        --state-hz 30
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import threading
import time
from typing import Any, Optional

from voice_bridge_server import (
    JointStateStore,
    LatestCommandStore,
    latest_command_store,
    latest_joint_state_store,
    serve,
)


log = logging.getLogger("smolvla_voice")


def _start_bridge_thread(host: str, port: int, store: LatestCommandStore) -> threading.Thread:
    def _run():
        asyncio.run(serve(host, port, store, latest_joint_state_store))

    t = threading.Thread(target=_run, name="voice-bridge", daemon=True)
    t.start()
    return t


def _build_robot(robot_type: str, port: str, robot_id: str) -> Any:
    """Instantiate a LeRobot Robot from CLI args.

    Currently wires up the common SO-follower family. Extend as needed for
    other robots by adding branches here or switching to config files.
    """
    if robot_type in {"so100_follower", "so101_follower"}:
        from lerobot.robots.so_follower import (  # type: ignore[import-not-found]
            SOFollower,
            SOFollowerRobotConfig,
        )

        cfg = SOFollowerRobotConfig(port=port, id=robot_id, cameras={})
        robot = SOFollower(cfg)
    else:
        # Generic path: rely on LeRobot's config-driven factory. We construct a
        # minimal config by dispatching on `type`.
        from lerobot.robots.config import RobotConfig  # type: ignore[import-not-found]
        from lerobot.robots.utils import make_robot_from_config  # type: ignore[import-not-found]

        cfg = RobotConfig.get_choice_class(robot_type)(port=port, id=robot_id)  # type: ignore[call-arg]
        robot = make_robot_from_config(cfg)

    robot.connect()
    log.info("robot %s connected on %s", robot_type, port)
    return robot


def _start_state_poller(
    robot: Any,
    hz: float,
    store: JointStateStore,
    stop_event: threading.Event,
) -> threading.Thread:
    """Poll ``robot.get_observation()`` at ``hz`` and publish joint positions.

    Only the scalar "<motor>.pos" entries are forwarded. Camera frames from
    the observation dict are ignored here - they'd saturate the socket and
    should be streamed separately if needed.
    """
    period = 1.0 / max(1.0, hz)

    def _run() -> None:
        log.info("joint-state poller running at %.1f Hz", hz)
        next_t = time.monotonic()
        while not stop_event.is_set():
            try:
                obs = robot.get_observation()
            except Exception as exc:  # pragma: no cover - hardware path
                log.warning("get_observation() failed: %s", exc)
                time.sleep(period)
                continue

            positions = {
                k: float(v) for k, v in obs.items()
                if isinstance(k, str) and k.endswith(".pos")
            }
            if positions:
                store.update(positions)

            next_t += period
            sleep_for = next_t - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                # Fell behind; reset schedule to avoid burning CPU catching up.
                next_t = time.monotonic()

    t = threading.Thread(target=_run, name="joint-state-poller", daemon=True)
    t.start()
    return t


def _load_policy(model_id: str):
    import torch
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("loading SmolVLA policy %s on %s", model_id, device)
    policy = SmolVLAPolicy.from_pretrained(model_id).to(device).eval()
    preprocess, postprocess = make_pre_post_processors(
        policy.config,
        model_id,
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )
    return policy, preprocess, postprocess, device


def _build_frame(task: str):
    """Return an input frame for SmolVLA.

    TODO: replace the stub with real camera images and robot proprio state.
    The dict keys must match what your SmolVLA config expects; see
    `lerobot/src/lerobot/policies/smolvla/configuration_smolvla.py`.
    """
    raise NotImplementedError(
        "Wire this to your real cameras / robot state before running. "
        "See lerobot-record for a reference."
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model-id", default="lerobot/smolvla_base")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--log-level", default="INFO")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not load SmolVLA or run inference; just log incoming commands.",
    )
    p.add_argument(
        "--robot-type",
        default=None,
        help=(
            "Optional LeRobot robot type (e.g. so100_follower). If set, a "
            "background poller will read joint positions and publish them "
            "over the bridge."
        ),
    )
    p.add_argument("--robot-port", default=None, help="Serial port for the robot.")
    p.add_argument("--robot-id", default="default", help="LeRobot robot id (calibration name).")
    p.add_argument(
        "--state-hz",
        type=float,
        default=30.0,
        help="Rate at which joint positions are polled and published (Hz).",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    _start_bridge_thread(args.host, args.port, latest_command_store)
    log.info("voice bridge ws://%s:%d", args.host, args.port)

    stop_event = threading.Event()
    robot: Optional[Any] = None
    poller: Optional[threading.Thread] = None
    if args.robot_type is not None:
        if args.robot_port is None:
            raise SystemExit("--robot-port is required when --robot-type is set")
        robot = _build_robot(args.robot_type, args.robot_port, args.robot_id)
        poller = _start_state_poller(
            robot, args.state_hz, latest_joint_state_store, stop_event
        )

    try:
        if args.dry_run:
            log.info("dry-run mode - waiting for transcripts...")
            while True:
                cmd = latest_command_store.wait_for_new(timeout=5.0)
                if cmd is None:
                    continue
                log.info("would dispatch task=%r to SmolVLA", cmd.text)
            return

        policy, preprocess, postprocess, device = _load_policy(args.model_id)

        import torch

        log.info("waiting for first voice command...")
        current_task: str | None = None
        while True:
            new_cmd = latest_command_store.wait_for_new(timeout=0.05)
            if new_cmd is not None:
                current_task = new_cmd.text
                log.info("task -> %r", current_task)

            if current_task is None:
                time.sleep(0.05)
                continue

            frame = _build_frame(current_task)
            batch = preprocess(frame)
            with torch.inference_mode():
                action = policy.select_action(batch)
                action = postprocess(action)

            # TODO: send `action` to your robot driver here.
            _ = action
    finally:
        stop_event.set()
        if poller is not None:
            poller.join(timeout=2.0)
        if robot is not None:
            try:
                robot.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    main()
