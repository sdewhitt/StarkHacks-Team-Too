"""Show a frame from every connected camera with its OpenCV index.

Usage:
    python scripts/show_cameras.py                # scan indices 0..9, show a grid
    python scripts/show_cameras.py --max-index 20 # scan more indices
    python scripts/show_cameras.py --save         # also save each frame as PNG
    python scripts/show_cameras.py --one-by-one   # open each camera in turn, press any key to continue

The idea: every OpenCV camera has an index (0, 1, 2, ...). On macOS those
indices are usually stable and start at 0; on Linux they can jump around
(e.g. 6, 16, 23) and may even change after a reboot or unplug. This script
grabs one frame from each index that responds and labels it, so you can
figure out which physical camera corresponds to which index and then plug
those indices into your LeRobot / SO-101 config.
"""

from __future__ import annotations

import argparse
import math
import os
import platform
import sys
from pathlib import Path

# MSMF compatibility fix on Windows (same as lerobot does).
if platform.system() == "Windows" and "OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS" not in os.environ:
    os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

try:
    import cv2
except ImportError:
    print("OpenCV is required. Install it with:  pip install opencv-python", file=sys.stderr)
    sys.exit(1)

import numpy as np


def _pick_backend() -> int:
    """Pick a sensible OpenCV capture backend for the current OS."""
    system = platform.system()
    if system == "Darwin":
        return cv2.CAP_AVFOUNDATION
    if system == "Linux":
        return cv2.CAP_V4L2
    if system == "Windows":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


def probe_camera(index: int, backend: int, warmup_frames: int = 2) -> np.ndarray | None:
    """Try to open camera `index` and return one frame, or None if unavailable."""
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return None

    frame = None
    try:
        # Some cameras return a black/empty frame on the first read, so grab a few.
        for _ in range(max(1, warmup_frames)):
            ok, f = cap.read()
            if ok and f is not None and f.size > 0:
                frame = f
    finally:
        cap.release()
    return frame


def annotate(frame: np.ndarray, index: int, backend_name: str) -> np.ndarray:
    """Draw the camera index and resolution on top of the frame."""
    img = frame.copy()
    h, w = img.shape[:2]
    label = f"Camera index: {index}"
    sub = f"{w}x{h}  ({backend_name})"

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, 70), (0, 0, 0), thickness=-1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)

    cv2.putText(img, label, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, sub, (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def build_grid(frames: list[np.ndarray], tile_w: int = 480) -> np.ndarray:
    """Tile frames into a single grid image."""
    if not frames:
        return np.zeros((200, 400, 3), dtype=np.uint8)

    resized: list[np.ndarray] = []
    for f in frames:
        h, w = f.shape[:2]
        scale = tile_w / w
        resized.append(cv2.resize(f, (tile_w, int(h * scale))))

    tile_h = max(f.shape[0] for f in resized)
    tiles = []
    for f in resized:
        if f.shape[0] < tile_h:
            pad = np.zeros((tile_h - f.shape[0], f.shape[1], 3), dtype=np.uint8)
            f = np.vstack([f, pad])
        tiles.append(f)

    cols = min(len(tiles), 3)
    rows = math.ceil(len(tiles) / cols)

    blank = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
    while len(tiles) < rows * cols:
        tiles.append(blank)

    grid_rows = []
    for r in range(rows):
        grid_rows.append(np.hstack(tiles[r * cols : (r + 1) * cols]))
    return np.vstack(grid_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-index", type=int, default=10, help="Highest camera index to probe (default: 10).")
    parser.add_argument("--save", action="store_true", help="Save each detected camera's frame as PNG.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/camera_preview"),
        help="Where to save PNGs when --save is set.",
    )
    parser.add_argument(
        "--one-by-one",
        action="store_true",
        help="Show each camera in its own window sequentially instead of a grid.",
    )
    args = parser.parse_args()

    backend = _pick_backend()
    backend_name = {
        cv2.CAP_AVFOUNDATION: "AVFoundation",
        cv2.CAP_V4L2: "V4L2",
        cv2.CAP_DSHOW: "DirectShow",
        cv2.CAP_ANY: "Any",
    }.get(backend, "Unknown")

    print(f"Scanning camera indices 0..{args.max_index} with backend: {backend_name}")

    detected: list[tuple[int, np.ndarray]] = []
    for idx in range(args.max_index + 1):
        frame = probe_camera(idx, backend)
        if frame is None:
            continue
        h, w = frame.shape[:2]
        print(f"  index {idx:>2}: OK  ({w}x{h})")
        detected.append((idx, annotate(frame, idx, backend_name)))

    if not detected:
        print("\nNo cameras detected. On Linux check permissions (e.g. `sudo usermod -aG video $USER`).")
        return 1

    print(f"\nDetected {len(detected)} camera(s).")

    if args.save:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for idx, frame in detected:
            path = args.output_dir / f"camera_{idx}.png"
            cv2.imwrite(str(path), frame)
            print(f"Saved {path}")

    if args.one_by_one:
        for idx, frame in detected:
            title = f"Camera index {idx}  (press any key for next, q to quit)"
            cv2.imshow(title, frame)
            key = cv2.waitKey(0) & 0xFF
            cv2.destroyWindow(title)
            if key == ord("q"):
                break
    else:
        grid = build_grid([f for _, f in detected])
        cv2.imshow("LeRobot camera indices (press any key to close)", grid)
        cv2.waitKey(0)

    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
