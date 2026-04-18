# Digital Twin Data Integration

This project now exposes two robot-state endpoints:

- `POST /robot_state`: publish robot state updates (JSON)
- `GET /robot_state/stream`: browser stream used by the A-Frame twin (SSE)

## 1) Run the web server

From the `meta-quest-camera-feed` folder:

```powershell
python server.py
```

Open `http://<your-ip>:5000` from the Meta Quest browser.

## 2) Verify the twin updates before wiring hardware

From the same folder, run the included simulator sender:

```powershell
python send_robot_state_example.py --server http://127.0.0.1:5000 --simulate
```

You should see the digital twin moving even with no robot attached.

## 3) Required robot data

Your robot-side script must send the following payload fields:

```json
{
  "basePosition": {"x": 0.0, "y": 1.15, "z": -1.4},
  "baseRotation": {"x": 0.0, "y": 180.0, "z": 0.0},
  "joints": {
    "shoulder": 15.0,
    "elbow": -25.0,
    "wrist": 10.0,
    "wristRotate": 0.0,
    "gripper": 0.03
  },
  "target": {"x": 0.25, "y": 1.3, "z": -1.0},
  "timestamp": 1713456000.0
}
```

Units expected by the frontend:

- `basePosition`, `target`: meters in world frame
- `baseRotation`: degrees
- `joints.shoulder`, `joints.elbow`, `joints.wrist`, `joints.wristRotate`: degrees
- `joints.gripper`: meters of jaw gap (rough visual only)

## 4) Where to get each value from the robot

- `joints.*`:
  - Read directly from your robot SDK joint telemetry.
  - If your SDK reports radians, convert to degrees before sending.
- `basePosition` and `baseRotation`:
  - Start with a fixed manual estimate.
  - Use the UI sliders in the top-left to align visually.
  - Once aligned, copy those values into your sender script defaults.
- `target`:
  - Optional. Use commanded end-effector position or waypoint.
  - If unavailable, keep it static.

## 5) Minimal hardware integration flow

1. Copy `send_robot_state_example.py` to your robot control machine.
2. Replace `read_robot_arm_state_from_sdk()` with your SDK calls.
3. Keep the script running at ~20 Hz.
4. Watch the status badge in the web UI:
   - `Robot state stream connected` means browser is receiving data.

## 6) Notes for hackathon speed

- Do not chase perfect metric calibration.
- Use rough alignment and a stable update rate.
- If timing is tight, send only `joints` and leave `target` fixed.
