"""
Cone distance detector using color detection + known size (pinhole camera model).

Cones: small red sport cones — 50mm height, 196mm diameter.
Camera: Logitech C270 — 4.0mm focal length, 55° diagonal FOV.

Usage:
  python cone_detector.py
  Press 'q' to quit, 'm' to toggle mask debug view.
  Optional: press 'c' with cone at 50cm to fine-tune calibration.

Distance formula (pinhole model):
  distance = (KNOWN_WIDTH * focal_length_px) / pixel_width
"""

import math
import cv2
import numpy as np
import json
import os

# ── Cone physical dimensions (mm) ──────────────────────────────────────
KNOWN_WIDTH_MM = 196.0   # cone diameter in mm
KNOWN_HEIGHT_MM = 50.0   # cone height in mm

# ── Camera specs: Logitech C270 ───────────────────────────────────────
CAMERA_DFOV_DEG = 55.0   # diagonal field of view in degrees
FRAME_WIDTH = 640
FRAME_HEIGHT = 480

# ── Calibration override (optional) ───────────────────────────────────
CALIBRATION_DISTANCE_MM = 500.0  # for manual fine-tune: place cone at 50cm
CALIBRATION_FILE = "cone_calibration.json"

# ── HSV ranges for RED (red wraps around hue=0/180) ───────────────────
# Tune these if detection is poor — press 'm' to see the mask
RED_LOWER_1 = np.array([0, 100, 80])
RED_UPPER_1 = np.array([10, 255, 255])
RED_LOWER_2 = np.array([160, 100, 80])
RED_UPPER_2 = np.array([180, 255, 255])

# ── Min contour area to filter noise (pixels²) ────────────────────────
MIN_CONTOUR_AREA = 500


def compute_focal_length_px(frame_w, frame_h, dfov_deg):
    """Compute focal length in pixels from diagonal FOV and resolution."""
    diag_px = math.sqrt(frame_w ** 2 + frame_h ** 2)
    dfov_rad = math.radians(dfov_deg)
    focal_px = (diag_px / 2.0) / math.tan(dfov_rad / 2.0)
    return focal_px


def load_calibration():
    if os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE) as f:
            data = json.load(f)
            return data.get("focal_length")
    return None


def save_calibration(focal_length):
    with open(CALIBRATION_FILE, "w") as f:
        json.dump({"focal_length": focal_length}, f, indent=2)
    print(f"[OK] Calibration saved: focal_length = {focal_length:.1f} px")


def detect_red_cones(frame):
    """Detect red regions and return list of (x, y, w, h, area) bounding rects."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Two masks for red (wraps around H=0)
    mask1 = cv2.inRange(hsv, RED_LOWER_1, RED_UPPER_1)
    mask2 = cv2.inRange(hsv, RED_LOWER_2, RED_UPPER_2)
    mask = mask1 | mask2

    # Clean up noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detections = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < MIN_CONTOUR_AREA:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        detections.append((x, y, w, h, area))

    return detections, mask


def estimate_distance(pixel_width, focal_length):
    """Pinhole model: distance = (real_width * focal_length) / pixel_width"""
    if pixel_width == 0:
        return float("inf")
    return (KNOWN_WIDTH_MM * focal_length) / pixel_width


def draw_detections(frame, detections, focal_length):
    """Draw bounding boxes and distance labels on frame."""
    for (x, y, w, h, area) in detections:
        dist_mm = estimate_distance(w, focal_length)
        dist_cm = dist_mm / 10.0
        color = (0, 255, 0)  # green

        if dist_cm < 30:
            color = (0, 0, 255)    # red = close
        elif dist_cm < 100:
            color = (0, 165, 255)  # orange = medium

        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
        label = f"{dist_cm:.0f}cm ({w}px)"
        cv2.putText(frame, label, (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_status(frame, focal_length, detections, is_custom_cal):
    """Draw status bar at the top."""
    h, w = frame.shape[:2]
    cv2.rectangle(frame, (0, 0), (w, 35), (0, 0, 0), -1)

    cal_src = "custom" if is_custom_cal else "auto/C270"
    text = f"f={focal_length:.0f}px ({cal_src}) | Cones: {len(detections)} | 'c'=calibrate 'm'=mask 'q'=quit"
    cv2.putText(frame, text, (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)


def main():
    cap = cv2.VideoCapture(0)  # change to 1 or 2 if needed
    if not cap.isOpened():
        print("Could not open camera")
        raise SystemExit

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    # Read actual resolution (camera may not support requested)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[OK] Camera opened at {actual_w}x{actual_h}")

    # Compute focal length from camera specs
    auto_focal = compute_focal_length_px(actual_w, actual_h, CAMERA_DFOV_DEG)
    print(f"[OK] Auto focal length from 55° dFoV: {auto_focal:.1f} px")

    # Check for manual calibration override
    custom_focal = load_calibration()
    is_custom_cal = False
    if custom_focal:
        focal_length = custom_focal
        is_custom_cal = True
        print(f"[OK] Using custom calibration: {focal_length:.1f} px")
    else:
        focal_length = auto_focal
        print(f"[OK] Using auto calibration. Press 'c' at 50cm to fine-tune.")

    show_mask = False

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to read frame")
            break

        detections, mask = detect_red_cones(frame)

        # Sort by area (largest = closest) for display priority
        detections.sort(key=lambda d: d[4], reverse=True)

        draw_detections(frame, detections, focal_length)
        draw_status(frame, focal_length, detections, is_custom_cal)

        cv2.imshow("Cone Detector", frame)

        if show_mask:
            cv2.imshow("Red Mask (debug)", mask)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break

        elif key == ord("c"):
            # Fine-tune calibration: place cone at 50cm
            if detections:
                largest = detections[0]
                pixel_w = largest[2]
                focal_length = (pixel_w * CALIBRATION_DISTANCE_MM) / KNOWN_WIDTH_MM
                is_custom_cal = True
                save_calibration(focal_length)
                print(f"[OK] Custom vs auto: {focal_length:.1f} vs {auto_focal:.1f} px")
            else:
                print("[!!] No cone detected — can't calibrate.")

        elif key == ord("r"):
            # Reset to auto calibration
            focal_length = auto_focal
            is_custom_cal = False
            if os.path.exists(CALIBRATION_FILE):
                os.remove(CALIBRATION_FILE)
            print("[OK] Reset to auto calibration.")

        elif key == ord("m"):
            show_mask = not show_mask
            if not show_mask:
                cv2.destroyWindow("Red Mask (debug)")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
