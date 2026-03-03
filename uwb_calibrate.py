#!/usr/bin/env python3
"""
UWB Per-Anchor Antenna Delay Calibration

Place the tag at 2-3 known positions, collect raw ranges, compute per-anchor
bias, and save corrections to uwb_calibration.json.

Usage:
    python3 uwb_calibrate.py
"""

import serial
import re
import time
import json
import os
import sys
import numpy as np
import math

# --- Reused from uwb_node.py ---
ANCHORS = {
    '029F': np.array([0.00, 0.00]),
    '0816': np.array([3.50, 0.00]),
    'DB9A': np.array([0.00, 3.00]),
    'DC06': np.array([3.50, 3.00]),
}
MAX_DISTANCE = 5.0
SERIAL_PORT = '/dev/serial/by-id/usb-SEGGER_J-Link_000760180803-if00'
BAUD_RATE = 115200
ANCHOR_PATTERN = re.compile(r'([0-9A-Fa-f]{4})\[\d+\.\d+,\d+\.\d+,\d+\.\d+\]=(\d+\.\d+)')

SUGGESTED_POSITIONS = [
    (1.75, 1.50, "center of field"),
    (0.50, 0.50, "near anchor 029F"),
    (3.00, 2.50, "near anchor DC06"),
]

COLLECTION_SECONDS = 10


def connect_serial():
    """Open serial port and send init sequence (same as uwb_node.py)."""
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    print(f"Connected to UWB tag on {SERIAL_PORT}")
    time.sleep(1)
    ser.write(b'\r')
    time.sleep(0.1)
    ser.write(b'\r')
    time.sleep(1)
    ser.reset_input_buffer()
    ser.write(b'les\r')
    time.sleep(0.5)
    ser.reset_input_buffer()
    return ser


def collect_ranges(ser, duration_s):
    """Collect raw distance readings for `duration_s` seconds.
    Returns dict: anchor_id -> list of raw distances."""
    ranges = {aid: [] for aid in ANCHORS}
    buf = ''
    end_time = time.time() + duration_s
    count = 0

    while time.time() < end_time:
        if ser.in_waiting:
            raw = ser.read(ser.in_waiting)
            buf += raw.decode('utf-8', errors='ignore')

            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                line = line.strip()
                if not line:
                    continue
                matches = ANCHOR_PATTERN.findall(line)
                for anchor_id, dist_str in matches:
                    anchor_id = anchor_id.upper()
                    d = float(dist_str)
                    if anchor_id in ANCHORS and 0.05 < d < MAX_DISTANCE:
                        ranges[anchor_id].append(d)
                        count += 1
        else:
            time.sleep(0.01)

    print(f"  Collected {count} total readings")
    for aid in sorted(ranges):
        n = len(ranges[aid])
        if n > 0:
            med = np.median(ranges[aid])
            print(f"    {aid}: {n} readings, median={med:.4f}m")
        else:
            print(f"    {aid}: no readings")
    return ranges


def compute_actual_distances(tag_pos):
    """Compute true distances from tag position to each anchor."""
    tx, ty = tag_pos
    actual = {}
    for aid, apos in ANCHORS.items():
        actual[aid] = math.sqrt((tx - apos[0])**2 + (ty - apos[1])**2)
    return actual


def prompt_position(index, suggestion):
    """Prompt the user to enter the tag's actual position."""
    sx, sy, desc = suggestion
    print(f"\n--- Position {index + 1} ---")
    print(f"Suggested: ({sx:.2f}, {sy:.2f}) — {desc}")
    print("Place the tag at a known position and enter its coordinates.")
    print("Press Enter to use the suggested position, or type x,y:")

    user_input = input("> ").strip()
    if not user_input:
        return (sx, sy)

    parts = user_input.replace(' ', '').split(',')
    if len(parts) != 2:
        print("Invalid input, using suggested position.")
        return (sx, sy)
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        print("Invalid input, using suggested position.")
        return (sx, sy)


def main():
    print("=== UWB Per-Anchor Antenna Delay Calibration ===\n")
    print(f"Anchors: {', '.join(sorted(ANCHORS.keys()))}")
    print(f"Collection time per position: {COLLECTION_SECONDS}s\n")

    try:
        ser = connect_serial()
    except serial.SerialException as e:
        print(f"Error: Could not open serial port: {e}")
        sys.exit(1)

    # Ask how many positions
    print(f"\nHow many calibration positions? (2-3, default=3)")
    n_input = input("> ").strip()
    n_positions = 3
    if n_input:
        try:
            n_positions = max(2, min(3, int(n_input)))
        except ValueError:
            pass

    # Collect data at each position
    position_data = []  # list of (tag_pos, ranges_dict)

    for i in range(n_positions):
        suggestion = SUGGESTED_POSITIONS[i] if i < len(SUGGESTED_POSITIONS) else SUGGESTED_POSITIONS[0]
        tag_pos = prompt_position(i, suggestion)
        print(f"Using position: ({tag_pos[0]:.2f}, {tag_pos[1]:.2f})")

        input("Press Enter when the tag is in place to start collecting...")
        print(f"Collecting ranges for {COLLECTION_SECONDS} seconds...")
        ranges = collect_ranges(ser, COLLECTION_SECONDS)
        position_data.append((tag_pos, ranges))

    # Close serial
    ser.write(b'\r')
    ser.close()
    print("\nSerial port closed.")

    # Compute per-anchor bias across all positions
    anchor_biases = {aid: [] for aid in ANCHORS}

    for tag_pos, ranges in position_data:
        actual = compute_actual_distances(tag_pos)
        for aid in ANCHORS:
            if len(ranges[aid]) >= 5:
                measured_median = float(np.median(ranges[aid]))
                bias = measured_median - actual[aid]
                anchor_biases[aid].append(bias)

    # Average bias per anchor
    print("\n=== Calibration Results ===")
    calibration = {}
    for aid in sorted(ANCHORS.keys()):
        biases = anchor_biases[aid]
        if biases:
            avg_bias = float(np.mean(biases))
            calibration[aid] = {"bias": round(avg_bias, 4)}
            print(f"  {aid}: bias = {avg_bias:+.4f}m (from {len(biases)} positions)")
        else:
            calibration[aid] = {"bias": 0.0}
            print(f"  {aid}: no data — bias set to 0.0")

    # Save to JSON
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uwb_calibration.json')
    with open(output_path, 'w') as f:
        json.dump(calibration, f, indent=2)
    print(f"\nCalibration saved to {output_path}")
    print("Restart uwb_node.py to apply corrections.")


if __name__ == '__main__':
    main()
