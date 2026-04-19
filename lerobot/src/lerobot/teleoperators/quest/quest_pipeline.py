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

from pathlib import Path
from typing import Any

from lerobot.model.kinematics import RobotKinematics
from lerobot.processor import DataProcessorPipeline
from lerobot.robots.so_follower.robot_kinematic_processor import (
    EEBoundsAndSafety,
    EEReferenceAndDelta,
    ForwardKinematicsJointsToEE,
    GripperVelocityToJoint,
    InverseKinematicsEEToJoints,
)

try:
    from .config_quest_teleop import QuestTeleopConfig
except ImportError:  # pragma: no cover - enables direct execution as a script
    from lerobot.teleoperators.quest.config_quest_teleop import QuestTeleopConfig

SO101_URDF_PATH = Path("./SO101/so101_new_calib.urdf")


def _build_kinematics_solver(motor_names: list[str]) -> RobotKinematics | None:
    # Same binding strategy as phone teleop examples: build a RobotKinematics solver from SO-101 URDF.
    try:
        return RobotKinematics(
            urdf_path=str(SO101_URDF_PATH),
            target_frame_name="gripper_frame_link",
            joint_names=motor_names,
        )
    except Exception:
        return None


def _get_motor_names(robot: Any) -> list[str]:
    if hasattr(robot, "bus") and hasattr(robot.bus, "motors"):
        return list(robot.bus.motors.keys())
    return ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]


def build_quest_so101_pipelines(robot: Any, config: QuestTeleopConfig):
    """Returns (teleop_to_dataset, dataset_to_robot, robot_to_dataset)."""

    motor_names = _get_motor_names(robot)
    kinematics = _build_kinematics_solver(motor_names)
    assert (
        kinematics is not None
    ), (
        "Quest pipeline could not initialize SO-101 kinematics. "
        f"Please provide the SO-101 URDF at '{SO101_URDF_PATH}'."
    )

    teleop_to_dataset = DataProcessorPipeline(
        steps=[
            EEReferenceAndDelta(
                kinematics=kinematics,
                motor_names=motor_names,
                end_effector_step_sizes={"x": 0.5, "y": 0.5, "z": 0.5, "wx": 10.0, "wy": 10.0, "wz": 10.0},
            ),
            EEBoundsAndSafety(
                end_effector_bounds={"min": config.ee_bounds_min, "max": config.ee_bounds_max},
                max_ee_step_m=config.max_ee_step_m,
            ),
            GripperVelocityToJoint(),
        ],
        name="quest_teleop_to_dataset",
    )

    dataset_to_robot = DataProcessorPipeline(
        steps=[
            InverseKinematicsEEToJoints(
                kinematics=kinematics,
                motor_names=motor_names,
            )
        ],
        name="quest_dataset_to_robot",
    )

    robot_to_dataset = DataProcessorPipeline(
        steps=[
            ForwardKinematicsJointsToEE(
                kinematics=kinematics,
                motor_names=motor_names,
            )
        ],
        name="quest_robot_to_dataset",
    )

    return teleop_to_dataset, dataset_to_robot, robot_to_dataset


def _pipeline_step_names(pipeline: DataProcessorPipeline) -> list[str]:
    return [step.__class__.__name__ for step in pipeline.steps]


if __name__ == "__main__":
    class _DummyRobot:
        def __init__(self):
            self.bus = type("Bus", (), {"motors": {"shoulder_pan": object(), "shoulder_lift": object(), "elbow_flex": object(), "wrist_flex": object(), "wrist_roll": object(), "gripper": object()}})()

    robot = _DummyRobot()
    config = QuestTeleopConfig()
    teleop_to_dataset, dataset_to_robot, robot_to_dataset = build_quest_so101_pipelines(robot, config)
    print("teleop_to_dataset:", _pipeline_step_names(teleop_to_dataset))
    print("dataset_to_robot:", _pipeline_step_names(dataset_to_robot))
    print("robot_to_dataset:", _pipeline_step_names(robot_to_dataset))


