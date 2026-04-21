# ControVirtual
Bridging physical robotics and immersive teleoperation.

- Honorable mention for "Best Use of AMD Tech" at [StarkHacks](https://devpost.com/software/team-too) 2026

## Project State (April 2026)

This repository is a hackathon-stage integration of:

- Meta Quest voice + XR client (Unity)
- Local Python voice bridge (WebSocket)
- Camera + digital-twin web server (Flask + OpenCV + A-Frame)
- SmolVLA/LeRobot policy assets and inference scaffolding

Current status by subsystem:

- Implemented and runnable: Quest voice capture, command bridge server, camera stream server, digital twin robot-state API, fake telemetry feeder.
- Partially implemented: SmolVLA loop wiring (`scripts/voice_bridge/run_smolvla_voice.py`) still requires hardware-specific observation frame construction.
- In progress/experimental: full end-to-end autonomous policy-to-robot loop for production hardware.

## What Works Today

### 1) Quest Voice -> Local Bridge

- Unity project in `quest-voice/` captures speech through Meta Voice SDK + Wit.ai.
- Commands are sent over WebSocket JSON to `scripts/voice_bridge/voice_bridge_server.py`.
- Latest command is persisted to `outputs/voice/latest_command.json`.

See: `quest-voice/README.md`

### 2) Camera Feed + Browser Digital Twin

- `meta-quest-camera-feed/server.py` serves:
	- `/video` (MJPEG camera stream)
	- `/robot_state` (GET/POST JSON state)
	- `/robot_state/stream` (SSE stream for web twin updates)
- `meta-quest-camera-feed/index.html` renders the stream and twin scene.

Integration notes: `meta-quest-camera-feed/ROBOT_STATE_INTEGRATION.md`

### 3) Voice + Robot State Test Harness (No Hardware)

- `scripts/voice_bridge/fake_robot_state_feeder.py` can:
	- run the voice bridge server,
	- publish realistic fake joint telemetry,
	- optionally mirror state into the Flask twin endpoint.

This is the fastest way to demo Quest + twin synchronization without a real arm.

### 4) Model Assets

- Policy/model artifacts are present in `model/`.
- SmolVLA-related directories (`smolvla_base/`, `smolvla_finetune/`) are included for policy workflows.

## Repository Map

- `quest-voice/`: Unity Quest app for voice capture + WebSocket command send.
- `meta-quest-camera-feed/`: Flask camera server + web digital twin.
- `scripts/voice_bridge/`: WebSocket bridge, fake feeders, and SmolVLA runner scaffold.
- `lerobot/`: upstream LeRobot codebase and docs.
- `model/`: local model card + weights/config artifacts.
- `outputs/voice/`: latest command state output.

## Quick Start (Windows / PowerShell)

From repository root:

```powershell
# 1) Activate venv (if present)
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& .\.venv\Scripts\Activate.ps1)

# 2) Install bridge dependencies
python -m pip install -r scripts/voice_bridge/requirements.txt

# 3) Start camera+twin web server (Terminal A)
python meta-quest-camera-feed/server.py

# 4) Start fake telemetry + voice bridge (Terminal B)
python scripts/voice_bridge/fake_robot_state_feeder.py --host 0.0.0.0 --port 8765 --hz 30 --http-server http://127.0.0.1:5000
```

Then:

- Open `http://127.0.0.1:5000` on your PC to verify camera/twin updates.
- In the Quest app, set WebSocket URL to `ws://<your-pc-lan-ip>:8765`.

## Running SmolVLA Voice Loop

Reference runner:

```powershell
python scripts/voice_bridge/run_smolvla_voice.py --dry-run
```

Important limitation:

- `scripts/voice_bridge/run_smolvla_voice.py` contains a `NotImplementedError` in `_build_frame(task)`.
- You must connect real camera + proprioception inputs before real policy inference control.

## Known Constraints

- Voice bridge joint state is process-local; state producers must run in the same process as the bridge server (or use an explicit external transport).
- Quest and host machine must be on the same network for WebSocket connectivity.
- Firewall must allow inbound TCP on port `8765` (or your chosen bridge port).

## Stack

- Languages: Python, C# (Unity)
- Core libraries/tools: LeRobot, PyTorch, Flask, OpenCV, websockets, Meta XR SDK, Wit.ai
- Hardware targets: Meta Quest 3/3S, SO-100/SO-101 follower arms (LeRobot ecosystem)

## Next Priorities

- Complete `_build_frame(task)` integration with real robot observations.
- Add a robust action-dispatch path from policy output to robot controllers.
- Add a single script/compose-style launcher for full demo bring-up.
- Expand test coverage for bridge protocol and twin state schema contracts.
