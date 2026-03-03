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
# Tighter saturation/value floors reject skin, brown, warm lighting.
RED_LOWER_1 = np.array([0, 110, 80])
RED_UPPER_1 = np.array([12, 255, 255])
RED_LOWER_2 = np.array([155, 110, 80])
RED_UPPER_2 = np.array([180, 255, 255])

# ── BGR channel ratio — red cone must have R dominate G and B ─────────
# This is the strongest false-positive killer: skin (R~G), brown (R~G~B),
# warm walls, wood, etc. all fail because their R channel doesn't dominate.
RED_RATIO_RG = 1.25    # R / G must exceed this (rejects skin/orange-brown)
RED_RATIO_RB = 1.40    # R / B must exceed this (rejects purple/pink/neutral)

# ── Shape filters ──────────────────────────────────────────────────────
MIN_CONTOUR_AREA = 300          # minimum pixels² to consider
MIN_SOLIDITY = 0.50             # contour area / convex hull area
MIN_ELLIPSE_PTS = 5             # minimum contour points needed to fit an ellipse


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
    """Detect red cone-shaped blobs.

    Returns (detections, rejected, mask) where each detection is
    (x, y, w, h, area, ellipse).

    Two-stage color filter:
      1. HSV mask — selects hue-red with high saturation/value.
      2. BGR ratio mask — requires R channel to dominate G and B.
         This kills skin, brown wood, warm walls, orange fabric, etc.
         that leak through HSV alone.

    Then morphological cleanup + contour extraction.
    """
    blurred = cv2.GaussianBlur(frame, (5, 5), 0)

    # ── Stage 1: HSV mask ─────────────────────────────────────────────
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, RED_LOWER_1, RED_UPPER_1)
    mask2 = cv2.inRange(hsv, RED_LOWER_2, RED_UPPER_2)
    mask = mask1 | mask2

    # ── Stage 2: BGR channel ratio ────────────────────────────────────
    # On the blurred image, check that R dominates G and B.
    b, g, r = cv2.split(blurred)
    r_f = r.astype(np.float32) + 1.0   # +1 avoids division by zero
    g_f = g.astype(np.float32) + 1.0
    b_f = b.astype(np.float32) + 1.0
    ratio_mask = (
        (r_f / g_f > RED_RATIO_RG) &
        (r_f / b_f > RED_RATIO_RB)
    ).astype(np.uint8) * 255
    mask = mask & ratio_mask

    # ── Morphological cleanup ─────────────────────────────────────────
    # Large close bridges gaps from white specular highlights on the cone
    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    detections = []
    rejected = []
    frame_h, frame_w = frame.shape[:2]

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < MIN_CONTOUR_AREA:
            continue

        x, y, w, h = cv2.boundingRect(cnt)

        # Solidity: contour area vs convex hull — reject spindly/noisy shapes
        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0
        if solidity < MIN_SOLIDITY:
            rejected.append((x, y, w, h, f"solid:{solidity:.2f}"))
            continue

        # Fit ellipse for drawing (not for filtering)
        ellipse = None
        if len(cnt) >= MIN_ELLIPSE_PTS:
            ellipse = cv2.fitEllipse(cnt)

        detections.append((x, y, w, h, area, ellipse))

    return detections, rejected, mask


def estimate_distance(x, y, w, h, focal_length, frame_w):
    """
    Pinhole model using width, but fall back to height when the cone
    is clipped by the frame edges (width is no longer reliable).
    """
    clipped = (x <= 1) or (x + w >= frame_w - 1)

    if clipped and h > 0:
        # Width is unreliable — use height instead
        dist_mm = (KNOWN_HEIGHT_MM * focal_length) / h
        return dist_mm, "H"
    elif w > 0:
        dist_mm = (KNOWN_WIDTH_MM * focal_length) / w
        return dist_mm, "W"
    else:
        return float("inf"), "?"


# ═══════════════════════════════════════════════════════════════════════
# Temporal smoothing — anchors detections across frames so cones don't
# flicker in and out when the camera angle shifts or a highlight causes
# a single-frame dropout.
# ═══════════════════════════════════════════════════════════════════════

class DetectionSmoother:
    """Keeps cone detections stable across frames.

    - Matches new detections to existing tracks by center distance.
    - Smooths position with an exponential moving average.
    - Holds a track for `hold_frames` after its last match so brief
      dropouts (glare, motion blur, angle change) don't kill it.
    """

    def __init__(self, hold_frames=15, match_distance=100, smooth=0.4):
        self.tracks = []
        self.hold_frames = hold_frames
        self.match_distance = match_distance
        self.smooth = smooth  # EMA factor (0=no update, 1=instant snap)

    def update(self, detections):
        """Feed raw detections, get back temporally-smoothed list."""
        matched_tracks = set()
        matched_dets = set()

        # Greedy nearest-center matching
        pairs = []
        for di, (x, y, w, h, area, ellipse) in enumerate(detections):
            cx, cy = x + w / 2.0, y + h / 2.0
            for ti, t in enumerate(self.tracks):
                d = math.hypot(cx - t['cx'], cy - t['cy'])
                pairs.append((d, di, ti))
        pairs.sort()

        for d, di, ti in pairs:
            if di in matched_dets or ti in matched_tracks:
                continue
            if d > self.match_distance:
                continue
            # Update track with EMA
            x, y, w, h, area, ellipse = detections[di]
            cx, cy = x + w / 2.0, y + h / 2.0
            t = self.tracks[ti]
            a = self.smooth
            t['cx'] = t['cx'] * (1 - a) + cx * a
            t['cy'] = t['cy'] * (1 - a) + cy * a
            t['w'] = t['w'] * (1 - a) + w * a
            t['h'] = t['h'] * (1 - a) + h * a
            t['area'] = area
            t['ellipse'] = ellipse
            t['missing'] = 0
            t['age'] += 1
            matched_tracks.add(ti)
            matched_dets.add(di)

        # Create new tracks for unmatched detections
        for di, (x, y, w, h, area, ellipse) in enumerate(detections):
            if di in matched_dets:
                continue
            self.tracks.append({
                'cx': x + w / 2.0, 'cy': y + h / 2.0,
                'w': float(w), 'h': float(h),
                'area': area, 'ellipse': ellipse,
                'age': 1, 'missing': 0,
            })

        # Tick missing for unmatched tracks
        for ti in range(len(self.tracks)):
            if ti not in matched_tracks:
                self.tracks[ti]['missing'] += 1

        # Purge expired
        self.tracks = [t for t in self.tracks if t['missing'] < self.hold_frames]

        # Return smoothed detections
        result = []
        for t in self.tracks:
            sx = int(t['cx'] - t['w'] / 2)
            sy = int(t['cy'] - t['h'] / 2)
            result.append((sx, sy, int(t['w']), int(t['h']), t['area'], t['ellipse']))
        return result


# ═══════════════════════════════════════════════════════════════════════
# Drawing helpers
# ═══════════════════════════════════════════════════════════════════════

def draw_detections(frame, detections, rejected, focal_length):
    """Draw bounding boxes and distance labels on frame."""
    frame_h, frame_w = frame.shape[:2]

    # Draw rejected items in blue with reason
    for (x, y, w, h, reason) in rejected:
        cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 150, 0), 1)
        cv2.putText(frame, reason, (x, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 150, 0), 1)

    # Draw accepted cones with distance + ellipse outline
    for (x, y, w, h, area, ellipse) in detections:
        dist_mm, mode = estimate_distance(x, y, w, h, focal_length, frame_w)
        dist_cm = dist_mm / 10.0
        color = (0, 255, 0)  # green

        if dist_cm < 30:
            color = (0, 0, 255)    # red = close
        elif dist_cm < 100:
            color = (0, 165, 255)  # orange = medium

        # Draw fitted ellipse outline instead of rectangle
        if ellipse is not None:
            cv2.ellipse(frame, ellipse, color, 2)
        else:
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        label = f"{dist_cm:.0f}cm [{mode}]"
        cv2.putText(frame, label, (x, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_path_overlay(frame, detections, focal_length):
    """Draw the greedy nearest-neighbor path the robot would take (same as cone_chaser)."""
    if not detections:
        return

    frame_h, frame_w = frame.shape[:2]

    # Build list of (center_x, center_y, distance_mm) for each detection
    cones = []
    for (x, y, w, h, area, ellipse) in detections:
        cx = x + w // 2
        cy = y + h // 2
        dist_mm, _ = estimate_distance(x, y, w, h, focal_length, frame_w)
        cones.append((cx, cy, dist_mm))

    # Greedy nearest-neighbor from robot (bottom center of frame)
    robot = (frame_w // 2, frame_h)
    remaining = list(range(len(cones)))
    order = []
    current = robot

    while remaining:
        best_i = None
        best_dist = float('inf')
        for i in remaining:
            dx = cones[i][0] - current[0]
            dy = cones[i][1] - current[1]
            d = math.sqrt(dx * dx + dy * dy)
            if d < best_dist:
                best_dist = d
                best_i = i
        order.append(best_i)
        current = (cones[best_i][0], cones[best_i][1])
        remaining.remove(best_i)

    # Draw path lines with semi-transparent overlay
    overlay = frame.copy()
    PATH_COLOR = (0, 255, 255)  # yellow

    prev = robot
    for step, idx in enumerate(order):
        cx, cy, dist_mm = cones[idx]
        pt = (cx, cy)

        # Path line
        cv2.line(overlay, prev, pt, PATH_COLOR, 2, cv2.LINE_AA)

        # Numbered circle at cone
        cv2.circle(overlay, pt, 14, PATH_COLOR, -1)
        cv2.circle(overlay, pt, 14, (0, 0, 0), 2)
        cv2.putText(overlay, str(step + 1), (cx - 5, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

        prev = pt

    # Blend overlay at 70% opacity
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

    # Robot marker (triangle at bottom center)
    rc = (frame_w // 2, frame_h - 10)
    tri = np.array([
        [rc[0], rc[1] - 16],
        [rc[0] - 10, rc[1]],
        [rc[0] + 10, rc[1]],
    ])
    cv2.fillPoly(frame, [tri], PATH_COLOR)
    cv2.polylines(frame, [tri], True, (0, 0, 0), 2)

    # Path info bar
    total_dist_cm = sum(cones[idx][2] / 10.0 for idx in order)
    bar_y = frame_h - 45
    cv2.rectangle(frame, (0, bar_y), (frame_w, bar_y + 20), (0, 0, 0), -1)
    cv2.putText(frame, f"Path: {len(order)} cones | ~{total_dist_cm:.0f}cm total | 'p'=toggle path",
                (10, bar_y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, PATH_COLOR, 1)


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

    smoother = DetectionSmoother(hold_frames=15, match_distance=100, smooth=0.4)
    show_mask = False
    show_path = True

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Failed to read frame")
            break

        raw_detections, rejected, mask = detect_red_cones(frame)

        # Temporal smoothing — anchors detections across frames
        detections = smoother.update(raw_detections)

        # Sort by area (largest = closest) for display priority
        detections.sort(key=lambda d: d[4], reverse=True)

        draw_detections(frame, detections, rejected, focal_length)
        if show_path:
            draw_path_overlay(frame, detections, focal_length)
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

        elif key == ord("p"):
            show_path = not show_path
            print(f"[OK] Path overlay: {'ON' if show_path else 'OFF'}")

        elif key == ord("m"):
            show_mask = not show_mask
            if not show_mask:
                cv2.destroyWindow("Red Mask (debug)")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
