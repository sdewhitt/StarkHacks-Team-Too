"""Voice-command bridge between the Quest 3S and the LeRobot policy.

Runs a WebSocket server that handles two flows over a single socket:

1. Quest -> PC (voice commands):
    {"type": "command", "text": "pick up the red block", "ts": 1713480000.123}

2. PC -> Quest (live joint state, opt-in):
    Client sends: {"type": "subscribe_state", "hz": 30}
    Server pushes at up to the requested rate:
        {
          "type": "joint_state",
          "ts": 1713480000.456,
          "monotonic": 12345.678,
          "version": 42,
          "keys":   ["shoulder_pan.pos", "shoulder_lift.pos", ...],
          "values": [12.34, -5.67, ...]
        }
    Client can stop with: {"type": "unsubscribe_state"}

Parallel `keys`/`values` arrays are chosen so that Unity's built-in
`JsonUtility` can deserialize the payload without a third-party JSON lib.

State is exposed to the process that *drives* the robot via
`latest_joint_state_store.update(...)` (thread-safe). See
`run_smolvla_voice.py` for a poller that reads `robot.get_observation()`
on a fixed schedule and pushes the result in.

Standalone usage:
    python scripts/voice_bridge/voice_bridge_server.py --host 0.0.0.0 --port 8765

Then point the Quest app's RobotCommandClient.serverUrl at
    ws://<this-machine-lan-ip>:8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

try:
    import websockets
except ImportError as exc:  # pragma: no cover - import-time guidance
    raise SystemExit(
        "The 'websockets' package is required. Install it with:\n"
        "    pip install websockets\n"
    ) from exc


log = logging.getLogger("voice_bridge")


@dataclass(frozen=True)
class Command:
    text: str
    ts: float
    received_at: float

    def to_dict(self) -> dict:
        return {"text": self.text, "ts": self.ts, "received_at": self.received_at}


class LatestCommandStore:
    """Thread-safe holder for the most recent voice command."""

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

    def wait_for_new(self, timeout: Optional[float] = None) -> Optional[Command]:
        """Blocks until a new command arrives (or timeout), then returns it."""
        self._event.clear()
        if self._event.wait(timeout=timeout):
            return self.get()
        return None


class JointStateStore:
    """Thread-safe holder for the latest robot joint state snapshot.

    The producer (e.g. the SmolVLA loop or a dedicated poller thread that calls
    ``robot.get_observation()``) invokes :meth:`update`. Consumers on the
    asyncio side call :meth:`snapshot` to get the most recent readout along
    with a monotonically increasing ``version`` counter so they can skip
    re-sending duplicate frames.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: tuple[str, ...] = ()
        self._values: tuple[float, ...] = ()
        self._ts: float = 0.0
        self._monotonic: float = 0.0
        self._version: int = 0

    def update(self, positions: Mapping[str, float], ts: Optional[float] = None) -> None:
        # Preserve insertion order from the producer (Python 3.7+ dicts do).
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


async def _handle_connection(
    ws,
    cmd_store: LatestCommandStore,
    state_store: JointStateStore,
) -> None:
    peer = getattr(ws, "remote_address", "?")
    log.info("client connected: %s", peer)

    subscribed = False
    min_interval = 1.0 / 30.0
    last_version = -1
    last_sent_monotonic = 0.0
    stop = asyncio.Event()

    async def recv_loop() -> None:
        nonlocal subscribed, min_interval
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("non-json message from %s: %r", peer, raw)
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
                    try:
                        await ws.send(json.dumps({"type": "ack", "text": text}))
                    except Exception:
                        pass

                elif mtype == "subscribe_state":
                    try:
                        hz = float(msg.get("hz", 30.0))
                    except (TypeError, ValueError):
                        hz = 30.0
                    hz = max(1.0, min(hz, 200.0))
                    min_interval = 1.0 / hz
                    subscribed = True
                    log.info("client %s subscribed to state at %.1f Hz", peer, hz)

                elif mtype == "unsubscribe_state":
                    subscribed = False
                    log.info("client %s unsubscribed from state", peer)

                else:
                    # Ignore unknown message types but keep the socket open.
                    pass
        except websockets.ConnectionClosed:
            pass
        finally:
            stop.set()

    async def send_loop() -> None:
        nonlocal last_version, last_sent_monotonic
        # Poll a little faster than the requested rate so jitter stays low.
        tick = 0.005
        while not stop.is_set():
            if subscribed:
                version, payload = state_store.snapshot()
                if version != 0 and version != last_version:
                    now = time.monotonic()
                    if (now - last_sent_monotonic) >= min_interval:
                        try:
                            await ws.send(json.dumps(payload))
                            last_version = version
                            last_sent_monotonic = now
                        except websockets.ConnectionClosed:
                            stop.set()
                            return
                        except Exception as exc:
                            log.warning("send failed to %s: %s", peer, exc)
                            stop.set()
                            return
            await asyncio.sleep(tick)

    recv_task = asyncio.create_task(recv_loop())
    send_task = asyncio.create_task(send_loop())
    try:
        done, pending = await asyncio.wait(
            {recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    finally:
        log.info("client disconnected: %s", peer)


async def serve(
    host: str,
    port: int,
    store: LatestCommandStore,
    state_store: JointStateStore | None = None,
) -> None:
    state_store = state_store if state_store is not None else latest_joint_state_store

    async def handler(ws):
        await _handle_connection(ws, store, state_store)

    async with websockets.serve(handler, host, port, ping_interval=20, ping_timeout=20):
        log.info("voice bridge listening on ws://%s:%d", host, port)
        stop = asyncio.Event()

        def _shutdown(*_):
            log.info("shutting down voice bridge")
            stop.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _shutdown)
            except NotImplementedError:
                pass
        await stop.wait()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Quest <-> LeRobot voice bridge")
    p.add_argument("--host", default="0.0.0.0", help="bind address (default 0.0.0.0)")
    p.add_argument("--port", type=int, default=8765, help="bind port (default 8765)")
    p.add_argument(
        "--state-file",
        type=Path,
        default=Path("outputs/voice/latest_command.json"),
        help="JSON file updated with the latest command",
    )
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    latest_command_store._state_file = args.state_file  # type: ignore[attr-defined]
    asyncio.run(serve(args.host, args.port, latest_command_store, latest_joint_state_store))


if __name__ == "__main__":
    main()
