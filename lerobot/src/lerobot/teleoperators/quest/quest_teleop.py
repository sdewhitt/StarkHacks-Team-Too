#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from lerobot.types import RobotAction
from lerobot.utils.decorators import check_if_already_connected

from ..teleoperator import Teleoperator
from .config_quest_teleop import QuestTeleopConfig

logger = logging.getLogger(__name__)
SERVER_TIMEOUT_S = 5.0


class QuestTeleop(Teleoperator):
    config_class = QuestTeleopConfig
    name = "quest"

    def __init__(self, config: QuestTeleopConfig):
        super().__init__(config)
        self.config = config

        self._latest_pose = None
        self._pose_lock = threading.Lock()

        self._server = None
        self._server_loop = None
        self._server_thread = None
        self._server_ready = threading.Event()

    @property
    def is_connected(self) -> bool:
        return self._server is not None and self._server_loop is not None and self._server_thread is not None

    @property
    def action_features(self) -> dict:
        return {
            "target_x": float,
            "target_y": float,
            "target_z": float,
            "target_wx": float,
            "target_wy": float,
            "target_wz": float,
            "gripper_vel": float,
            "enabled": bool,
        }

    @property
    def feedback_features(self) -> dict:
        return {}

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        return None

    def configure(self) -> None:
        return None

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        del calibrate

        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - depends on optional runtime env
            raise ImportError(
                "Quest teleop requires the 'websockets' package. Install it in your runtime environment."
            ) from exc

        self._server_ready.clear()
        self._server_loop = asyncio.new_event_loop()
        self._server_thread = threading.Thread(target=self._run_server, args=(websockets,), daemon=True)
        self._server_thread.start()
        if not self._server_ready.wait(timeout=SERVER_TIMEOUT_S):
            self.disconnect()
            raise TimeoutError(
                f"Quest teleop server failed to start on {self.config.host}:{self.config.port} "
                f"within {SERVER_TIMEOUT_S} seconds"
            )

    def _run_server(self, websockets_module: Any) -> None:
        assert self._server_loop is not None
        loop = self._server_loop
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._start_server(websockets_module))
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop=loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _start_server(self, websockets_module: Any) -> None:
        self._server = await websockets_module.serve(self._handler, self.config.host, self.config.port)
        self._server_ready.set()
        logger.info("Quest teleop WebSocket server listening on %s:%s", self.config.host, self.config.port)

    async def _handler(self, websocket) -> None:
        async for message in websocket:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                logger.debug("Ignoring invalid JSON payload from Quest teleop: %r", message)
                continue

            if isinstance(payload, dict):
                with self._pose_lock:
                    self._latest_pose = payload

    def _read_pose(self):
        with self._pose_lock:
            return None if self._latest_pose is None else dict(self._latest_pose)

    @staticmethod
    def _unity_to_robot(x: float, y: float, z: float) -> tuple[float, float, float]:
        robot_x = z
        robot_y = -x
        robot_z = y
        return robot_x, robot_y, robot_z

    def get_action(self) -> RobotAction:
        pose = self._read_pose()
        if pose is None:
            return {}

        scale = float(self.config.coordinate_scale)
        unity_x = float(pose.get("target_x", pose.get("x", 0.0))) * scale
        unity_y = float(pose.get("target_y", pose.get("y", 0.0))) * scale
        unity_z = float(pose.get("target_z", pose.get("z", 0.0))) * scale
        robot_x, robot_y, robot_z = self._unity_to_robot(unity_x, unity_y, unity_z)

        return {
            "target_x": robot_x,
            "target_y": robot_y,
            "target_z": robot_z,
            "target_wx": float(pose.get("target_wx", pose.get("wx", 0.0))),
            "target_wy": float(pose.get("target_wy", pose.get("wy", 0.0))),
            "target_wz": float(pose.get("target_wz", pose.get("wz", 0.0))),
            "gripper_vel": float(pose.get("gripper_vel", 0.0)),
            "enabled": bool(pose.get("enabled", False)),
        }

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        logger.debug("Quest teleop feedback stub: %s", feedback)

    def disconnect(self) -> None:
        loop = self._server_loop
        server = self._server
        self._server = None
        self._server_loop = None

        if loop is None:
            self._server_thread = None
            return

        async def _shutdown() -> None:
            if server is not None:
                server.close()
                await server.wait_closed()

        fut = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        try:
            fut.result(timeout=SERVER_TIMEOUT_S)
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            logger.debug("Quest teleop shutdown error: %s", exc)

        loop.call_soon_threadsafe(loop.stop)
        if self._server_thread is not None and self._server_thread.is_alive():
            self._server_thread.join(timeout=SERVER_TIMEOUT_S)
        self._server_thread = None

    def __del__(self) -> None:
        try:
            self.disconnect()
        except Exception:
            pass



