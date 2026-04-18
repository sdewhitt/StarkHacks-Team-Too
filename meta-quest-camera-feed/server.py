# server.py
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
import cv2
import json
import threading
import time

app = Flask(__name__)


state_lock = threading.Lock()
robot_state = {
    "basePosition": {"x": 0.0, "y": 1.15, "z": -1.4},
    "baseRotation": {"x": 0.0, "y": 180.0, "z": 0.0},
    "joints": {
        "shoulder": 15.0,
        "elbow": -25.0,
        "wrist": 10.0,
        "wristRotate": 0.0,
        "gripper": 0.03,
    },
    "target": {"x": 0.25, "y": 1.3, "z": -1.0},
    "timestamp": time.time(),
}


def open_camera():
    # CAP_DSHOW is generally more reliable on Windows webcams.
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(0)
    return camera


cap = open_camera()


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


def parse_vec3(payload, key, default_value):
    candidate = payload.get(key)
    if not isinstance(candidate, dict):
        return default_value

    out = dict(default_value)
    for axis in ("x", "y", "z"):
        value = candidate.get(axis)
        if isinstance(value, (int, float)):
            out[axis] = float(value)
    return out


def parse_joints(payload, default_value):
    candidate = payload.get("joints")
    if not isinstance(candidate, dict):
        return default_value

    out = dict(default_value)
    for key, value in candidate.items():
        if isinstance(value, (int, float)):
            out[key] = float(value)

    # Safety limits for the simple twin rig.
    out["shoulder"] = clamp(out.get("shoulder", 0.0), -120.0, 120.0)
    out["elbow"] = clamp(out.get("elbow", 0.0), -150.0, 150.0)
    out["wrist"] = clamp(out.get("wrist", 0.0), -180.0, 180.0)
    out["wristRotate"] = clamp(out.get("wristRotate", 0.0), -180.0, 180.0)
    out["gripper"] = clamp(out.get("gripper", 0.03), 0.0, 0.12)
    return out


def merge_robot_state(payload):
    with state_lock:
        current_state = dict(robot_state)
        current_state["basePosition"] = parse_vec3(payload, "basePosition", current_state["basePosition"])
        current_state["baseRotation"] = parse_vec3(payload, "baseRotation", current_state["baseRotation"])
        current_state["joints"] = parse_joints(payload, current_state["joints"])
        current_state["target"] = parse_vec3(payload, "target", current_state["target"])

        # Convenience support for payloads using top-level x/y/z for end-effector target.
        if all(axis in payload for axis in ("x", "y", "z")):
            xyz = payload
            if all(isinstance(xyz[axis], (int, float)) for axis in ("x", "y", "z")):
                current_state["target"] = {
                    "x": float(xyz["x"]),
                    "y": float(xyz["y"]),
                    "z": float(xyz["z"]),
                }

        current_state["timestamp"] = float(payload.get("timestamp", time.time()))
        robot_state.update(current_state)
        return dict(robot_state)


def get_robot_state_snapshot():
    with state_lock:
        return dict(robot_state)

def generate():
    global cap
    while True:
        if cap is None or not cap.isOpened():
            cap = open_camera()
            if cap is None or not cap.isOpened():
                time.sleep(0.25)
                continue

        success, frame = cap.read()
        if not success:
            cap.release()
            cap = open_camera()
            time.sleep(0.05)
            continue

        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/video')
def video():
    return Response(
        generate(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
        },
    )


@app.route('/robot_state', methods=['GET'])
def get_robot_state():
    response = jsonify(get_robot_state_snapshot())
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/robot_state', methods=['POST'])
def post_robot_state():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'error': 'Expected a JSON object payload.'}), 400

    updated_state = merge_robot_state(payload)
    return jsonify({'ok': True, 'state': updated_state})


@app.route('/robot_state/stream', methods=['GET'])
def robot_state_stream():
    @stream_with_context
    def event_stream():
        while True:
            snapshot = get_robot_state_snapshot()
            yield f"data: {json.dumps(snapshot)}\\n\\n"
            time.sleep(0.1)

    return Response(
        event_stream(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


@app.route('/')
def index():
    return send_from_directory(app.root_path, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)