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

import logging
import time
from threading import Lock
from typing import Any

import numpy as np
from numpy.typing import NDArray

from lerobot.utils.decorators import check_if_already_connected
from lerobot.utils.errors import DeviceNotConnectedError

from ..camera import Camera
from .config_mjpeg_camera import MJPEGStreamCameraConfig

logger = logging.getLogger(__name__)


def _get_cv2():
    import cv2  # type: ignore

    return cv2


class MJPEGStreamCamera(Camera):
    def __init__(self, config: MJPEGStreamCameraConfig):
        super().__init__(config)
        self.config = config
        self.url = config.url
        self.capture = None
        self._lock = Lock()
        self._last_frame: NDArray[Any] | None = None
        self._last_frame_time: float | None = None
        self._allow_reconnect = False

    @property
    def is_connected(self) -> bool:
        return self.capture is not None and self.capture.isOpened()

    @staticmethod
    def find_cameras() -> list[dict[str, Any]]:
        return []

    @check_if_already_connected
    def connect(self, warmup: bool = True) -> None:
        del warmup
        cv2 = _get_cv2()
        self.capture = cv2.VideoCapture(self.url)
        if not self.capture.isOpened():
            self.capture.release()
            self.capture = None
            raise ConnectionError(f"Failed to open MJPEG stream: {self.url}")
        self._allow_reconnect = True
        logger.info("MJPEG stream camera connected: %s", self.url)

    def _read_once(self) -> NDArray[Any] | None:
        cv2 = _get_cv2()
        if self.capture is None:
            return None
        ok, frame_bgr = self.capture.read()
        if not ok or frame_bgr is None:
            return None
        return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

    def read(self) -> NDArray[Any]:
        if self.capture is None and not self._allow_reconnect:
            raise DeviceNotConnectedError(f"{self} is not connected")

        deadline = time.monotonic() + float(self.config.timeout_s)

        while True:
            frame = self._read_once()
            if frame is not None:
                with self._lock:
                    self._last_frame = frame
                    self._last_frame_time = time.monotonic()
                return frame

            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out reading MJPEG stream from {self.url}")

            self.disconnect()
            time.sleep(0.1)
            self.connect(warmup=False)

    def async_read(self, timeout_ms: float = 200) -> NDArray[Any]:
        del timeout_ms
        return self.read()

    def read_latest(self, max_age_ms: int = 500) -> NDArray[Any]:
        with self._lock:
            if self._last_frame is None or self._last_frame_time is None:
                raise RuntimeError("No MJPEG frame has been received yet.")
            age_ms = (time.monotonic() - self._last_frame_time) * 1000.0
            if age_ms > max_age_ms:
                raise TimeoutError(f"Latest MJPEG frame is too old ({age_ms:.1f} ms > {max_age_ms} ms)")
            return self._last_frame

    def disconnect(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self._allow_reconnect = False



