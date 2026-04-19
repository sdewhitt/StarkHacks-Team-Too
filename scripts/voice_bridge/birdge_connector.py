import time
from lerobot.robots.so_follower import SOFollower, SOFollowerRobotConfig
# Import the store from your provided server script
from voice_bridge_server import latest_joint_state_store

def run_telemetry():
    # 1. Setup your Robot (Change port to your actual robot port)
    config = SOFollowerRobotConfig(
        robot_type="so101_follower", 
        id="follower", 
        port="/dev/ttyUSB0" # Use "COM3" etc. on Windows
    )
    robot = SOFollower(config)
    robot.connect(calibrate=False) # Set to True if first time today

    print("Connected to Robot. Streaming to Quest...")

    try:
        while True:
            # 2. Get the live state from the robot
            obs = robot.get_observation()
            
            # 3. Map LeRobot names to your Unity GameObject names
            # IMPORTANT: The keys below must match your Unity Hierarchy names exactly!
            positions = {
                "shoulder_link": float(obs["shoulder_pan.pos"]),
                "upper_arm_link": float(obs["shoulder_lift.pos"]),
                "lower_arm_link": float(obs["elbow_flex.pos"]),
                "wrist_link": float(obs["wrist_flex.pos"]),
                "moving_jaw_so101_v1_link": float(obs["gripper.pos"])
            }

            # 4. Push to the store (The Quest server picks it up automatically)
            latest_joint_state_store.update(positions)
            
            time.sleep(0.01) # 100Hz polling rate
    finally:
        robot.disconnect()

if __name__ == "__main__":
    run_telemetry()