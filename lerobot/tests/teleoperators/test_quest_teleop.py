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

from lerobot.teleoperators.quest import QuestTeleop, QuestTeleopConfig


def test_config_registration():
    cfg = QuestTeleopConfig()
    assert cfg.type == "quest_teleop"


def test_teleop_init():
    cfg = QuestTeleopConfig()
    teleop = QuestTeleop(cfg)
    assert teleop.config is cfg
    assert not teleop.is_connected


def test_get_action_empty_before_connect():
    teleop = QuestTeleop(QuestTeleopConfig())
    assert teleop.get_action() == {}


def test_coordinate_remap():
    teleop = QuestTeleop(QuestTeleopConfig())
    teleop._latest_pose = {
        "target_x": 1.0,
        "target_y": 0.0,
        "target_z": 0.0,
        "target_wx": 0.0,
        "target_wy": 0.0,
        "target_wz": 0.0,
        "gripper_vel": 0.0,
        "enabled": True,
    }

    action = teleop.get_action()
    assert action["target_y"] == -1.0
    assert action["target_x"] == 0.0
    assert action["target_z"] == 0.0


def test_coordinate_scale():
    cfg = QuestTeleopConfig(coordinate_scale=2.0)
    teleop = QuestTeleop(cfg)
    teleop._latest_pose = {
        "target_x": 0.0,
        "target_y": 0.0,
        "target_z": 1.0,
        "target_wx": 0.0,
        "target_wy": 0.0,
        "target_wz": 0.0,
        "gripper_vel": 0.0,
        "enabled": True,
    }

    action = teleop.get_action()
    assert action["target_x"] == 2.0


def test_enabled_passthrough():
    teleop = QuestTeleop(QuestTeleopConfig())
    teleop._latest_pose = {
        "target_x": 0.0,
        "target_y": 0.0,
        "target_z": 0.0,
        "target_wx": 0.0,
        "target_wy": 0.0,
        "target_wz": 0.0,
        "gripper_vel": 0.0,
        "enabled": False,
    }

    action = teleop.get_action()
    assert action["enabled"] is False

