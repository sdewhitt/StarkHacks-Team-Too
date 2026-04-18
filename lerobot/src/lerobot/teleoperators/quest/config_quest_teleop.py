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

"""Configuration for Quest teleoperation."""

from dataclasses import dataclass, field

from ..config import TeleoperatorConfig


@TeleoperatorConfig.register_subclass("quest_teleop")
@dataclass
class QuestTeleopConfig(TeleoperatorConfig):
    host: str = "0.0.0.0"
    port: int = 8765
    coordinate_scale: float = 1.0
    max_ee_step_m: float = 0.05
    ee_bounds_min: list[float] = field(default_factory=lambda: [-0.4, -0.4, 0.0])
    ee_bounds_max: list[float] = field(default_factory=lambda: [0.4, 0.4, 0.6])

