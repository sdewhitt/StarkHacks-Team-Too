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

import numpy as np

from lerobot.cameras.mjpeg_stream import MJPEGStreamCamera, MJPEGStreamCameraConfig


class _FakeVideoCapture:
    def __init__(self, url: str):
        self.url = url
        self.opened = True
        self.read_count = 0
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        if not self.opened:
            return False, None
        self.read_count += 1
        frame_bgr = np.zeros((2, 3, 3), dtype=np.uint8)
        frame_bgr[..., 0] = 1
        return True, frame_bgr

    def release(self):
        self.released = True
        self.opened = False


class _FakeCv2:
    COLOR_BGR2RGB = 1

    def __init__(self):
        self.instances: list[_FakeVideoCapture] = []

    def VideoCapture(self, url):
        cap = _FakeVideoCapture(url)
        self.instances.append(cap)
        return cap

    def cvtColor(self, frame, code):
        del code
        return frame[..., ::-1].copy()


def test_config_registration():
    cfg = MJPEGStreamCameraConfig(url="http://localhost:8080/stream")
    assert cfg.type == "mjpeg_stream"
    assert cfg.name == "wrist"


def test_connect_read_disconnect(monkeypatch):
    fake_cv2 = _FakeCv2()
    monkeypatch.setattr("lerobot.cameras.mjpeg_stream.mjpeg_stream_camera._get_cv2", lambda: fake_cv2)

    camera = MJPEGStreamCamera(MJPEGStreamCameraConfig(url="http://localhost:8080/stream", timeout_s=0.1))
    camera.connect(warmup=False)

    assert camera.is_connected
    frame = camera.read()
    assert frame.shape == (2, 3, 3)
    assert frame[0, 0, 0] == 0  # RGB conversion reversed channels
    assert frame[0, 0, 2] == 1

    latest = camera.read_latest()
    assert latest.shape == frame.shape

    camera.disconnect()
    assert not camera.is_connected
    assert fake_cv2.instances[0].released is True


def test_auto_reconnect_on_dropped_stream(monkeypatch):
    fake_cv2 = _FakeCv2()
    monkeypatch.setattr("lerobot.cameras.mjpeg_stream.mjpeg_stream_camera._get_cv2", lambda: fake_cv2)

    camera = MJPEGStreamCamera(MJPEGStreamCameraConfig(url="http://localhost:8080/stream", timeout_s=0.1))
    camera.connect(warmup=False)
    assert camera.capture is not None

    # Simulate a dropped stream on the next read by closing the first capture.
    camera.capture.opened = False

    frame = camera.read()
    assert frame.shape == (2, 3, 3)
    assert len(fake_cv2.instances) >= 2


