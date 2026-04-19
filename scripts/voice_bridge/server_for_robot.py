from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import signal
import threading
import time
import lerobot
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional
from lerobot.robots.so_follower import SOFollower, SOFollowerRobotConfig

log = logging.getLogger("voice_bridge")
config = SOFollowerRobotConfig(
    robot_type="so101_follower", 
    id="follower", 
    port="/dev/ttyUSB0" # Use "COM3" etc. on Windows
)
robot = SOFollower(config)
robot.connect(calibrate=False)

@dataclass(frozen=True)
class Command:
    text: str
    ts: float
    received_at: float

    def to_dict(self) -> dict:
        return {"text": self.text, "ts": self.ts, "received_at": self.received_at}


class LatestCommandStore:
    def __init__(self, state_file: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._current: Optional[Command] = None
        self._event = threading.Event()
        self._state_file = state_file

    def set(self, command: Command) -> None:
        with self._lock:
            self._current = command
            self._event.set()

        if self._state_file is not None:
            try:
                self._state_file.parent.mkdir(parents=True, exist_ok=True)
                self._state_file.write_text(json.dumps(command.to_dict()))
            except OSError as exc:
                log.warning("Failed to write state file %s: %s", self._state_file, exc)

    def get(self) -> Optional[Command]:
        with self._lock:
            return self._current


class JointStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: tuple[str, ...] = ()
        self._values: tuple[float, ...] = ()
        self._ts: float = 0.0
        self._monotonic: float = 0.0
        self._version: int = 0

    def update(self, positions: Mapping[str, float], ts: Optional[float] = None) -> None:
        keys = tuple(positions.keys())
        values = tuple(float(v) for v in positions.values())
        now_wall = ts if ts is not None else time.time()
        now_mono = time.monotonic()

        with self._lock:
            self._keys = keys
            self._values = values
            self._ts = now_wall
            self._monotonic = now_mono
            self._version += 1

    def snapshot(self) -> tuple[int, dict]:
        with self._lock:
            return self._version, {
                "type": "joint_state",
                "ts": self._ts,
                "monotonic": self._monotonic,
                "version": self._version,
                "keys": list(self._keys),
                "values": list(self._values),
            }


latest_command_store = LatestCommandStore()
latest_joint_state_store = JointStateStore()


# ---------------- TCP CONNECTION HANDLER ---------------- #

async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    cmd_store: LatestCommandStore,
    state_store: JointStateStore,
):
    peer = writer.get_extra_info("peername")
    log.info("client connected: %s", peer)

    subscribed = True
    min_interval = 1.0 / 30.0
    last_version = -1
    last_sent = 0.0
    stop = False

    async def recv_loop():
        nonlocal subscribed, min_interval, stop

        while not stop:
            try:
                line = await reader.readline()
                if not line:
                    break

                try:
                    msg = json.loads(line.decode())
                except json.JSONDecodeError:
                    log.warning("invalid JSON from %s", peer)
                    continue

                mtype = msg.get("type")

                if mtype == "command":
                    text = (msg.get("text") or "").strip()
                    if not text:
                        continue

                    ts = float(msg.get("ts", time.time()))
                    cmd = Command(text=text, ts=ts, received_at=time.time())
                    cmd_store.set(cmd)

                    log.info("command: %s", text)

                    writer.write((json.dumps({"type": "ack", "text": text}) + "\n").encode())
                    await writer.drain()

                elif mtype == "subscribe_state":
                    hz = float(msg.get("hz", 30.0))
                    hz = max(1.0, min(hz, 200.0))
                    min_interval = 1.0 / hz
                    subscribed = True

                elif mtype == "unsubscribe_state":
                    subscribed = False

            except Exception:
                break

        stop = True

    async def send_loop():
        nonlocal last_version, last_sent, stop

        while not stop:
            if subscribed:
                now = time.monotonic()
                try:
                    obs = robot.get_observation()

                    positions = {
                        "shoulder_link": float(obs["shoulder_pan.pos"]),
                        "upper_arm_link": float(obs["shoulder_lift.pos"]),
                        "lower_arm_link": float(obs["elbow_flex.pos"]),
                        "wrist_link": float(obs["wrist_flex.pos"]),
                        "gripper_link": float(obs["wrist_roll.pos"]), # The 6th motion
                        "moving_jaw_so101_v1_link": float(obs["gripper.pos"])
                    }
                    latest_joint_state_store.update(positions)
                    version, payload = state_store.snapshot()
                    writer.write((json.dumps(payload) + "\n").encode())
                    await writer.drain()
                    last_version = version
                    last_sent = now
                except Exception:
                    break

            await asyncio.sleep(1)

        stop = True

    await asyncio.gather(recv_loop(), send_loop())

    writer.close()
    await writer.wait_closed()
    log.info("client disconnected: %s", peer)


# ---------------- SERVER ---------------- #

async def serve(host: str, port: int):
    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, latest_command_store, latest_joint_state_store),
        host,
        port,
    )

    log.info("TCP voice bridge listening on %s:%d", host, port)

    stop_event = asyncio.Event()

    def shutdown():
        log.info("shutting down")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass

    async with server:
        await stop_event.wait()


# ---------------- CLI ---------------- #

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(serve(args.host, args.port))


if __name__ == "__main__":
    main()