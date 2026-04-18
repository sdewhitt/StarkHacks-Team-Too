# server.py
from flask import Flask, Response, send_from_directory
import cv2
import time

app = Flask(__name__)


def open_camera():
    # CAP_DSHOW is generally more reliable on Windows webcams.
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        camera.release()
        camera = cv2.VideoCapture(0)
    return camera


cap = open_camera()

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


@app.route('/')
def index():
    return send_from_directory(app.root_path, 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)