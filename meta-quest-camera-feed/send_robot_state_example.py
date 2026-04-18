import argparse
import json
import math
import time
import urllib.error
import urllib.request


def post_json(url, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def read_robot_arm_state_from_sdk():
    """
    Replace this function with your robot arm SDK calls.

    Return a dict in this shape:
    {
      "basePosition": {"x": float, "y": float, "z": float},
      "baseRotation": {"x": float, "y": float, "z": float},
      "joints": {
        "shoulder": float,
        "elbow": float,
        "wrist": float,
        "wristRotate": float,
        "gripper": float
      },
      "target": {"x": float, "y": float, "z": float}
    }
    """
    raise NotImplementedError("Connect this to your robot SDK and return live values.")


def read_simulated_state(start_time):
    elapsed = time.time() - start_time
    shoulder = 25.0 * math.sin(elapsed * 0.6)
    elbow = -35.0 + 20.0 * math.sin(elapsed * 0.9)
    wrist = 10.0 * math.sin(elapsed * 1.4)
    wrist_rotate = 45.0 * math.sin(elapsed * 0.3)
    gripper = 0.03 + 0.01 * (1.0 + math.sin(elapsed * 1.8))

    return {
        "basePosition": {"x": 0.0, "y": 1.15, "z": -1.4},
        "baseRotation": {"x": 0.0, "y": 180.0, "z": 0.0},
        "joints": {
            "shoulder": shoulder,
            "elbow": elbow,
            "wrist": wrist,
            "wristRotate": wrist_rotate,
            "gripper": gripper,
        },
        "target": {"x": 0.25, "y": 1.3, "z": -1.0},
    }


def main():
    parser = argparse.ArgumentParser(description="Send robot arm state to the digital twin server.")
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:5000",
        help="Base URL for meta-quest-camera-feed server.",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=20.0,
        help="Update rate in Hz.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=1.5,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Send simulated robot data instead of real SDK data.",
    )
    args = parser.parse_args()

    post_url = args.server.rstrip("/") + "/robot_state"
    interval = 1.0 / max(1.0, args.hz)
    start_time = time.time()

    print(f"Streaming robot state to {post_url} at {args.hz:.1f} Hz")
    if args.simulate:
        print("Simulation mode is ON")

    while True:
        loop_start = time.time()
        try:
            if args.simulate:
                state = read_simulated_state(start_time)
            else:
                state = read_robot_arm_state_from_sdk()

            state["timestamp"] = time.time()
            post_json(post_url, state, timeout=args.timeout)
        except NotImplementedError as error:
            print(error)
            return
        except urllib.error.URLError as error:
            print(f"Post failed: {error}")

        elapsed = time.time() - loop_start
        sleep_for = interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)


if __name__ == "__main__":
    main()
