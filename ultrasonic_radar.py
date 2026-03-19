#!/usr/bin/env python3
"""
TurtleBot Ultrasonic Radar v2 — Rich dashboard + parallel sensor polling.

Usage:
    pip install rich --break-system-packages
    sudo PYTHONPATH=/home/ubuntu/.local/lib/python3.12/site-packages python3 radar.py

    --diag   Run sensor diagnostics only
"""

import sys
import time
import signal
import threading

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
except ImportError:
    print("Requires 'rich' library.  Install with:")
    print("  pip install rich --break-system-packages")
    sys.exit(1)

from grove.grove_ultrasonic_ranger import GroveUltrasonicRanger

# ── Config ────────────────────────────────────────────────
SENSORS = [
    ('FC', 5,  'FRONT CENTER'),
    ('FL', 18, 'FRONT LEFT'),
    ('FR', 16, 'FRONT RIGHT'),
    ('L',  22, 'LEFT'),
    ('R',  26, 'RIGHT'),
    ('BK', 24, 'BACK'),
]

DANGER   = 30       # cm
CAUTION  = 100      # cm
MAX_RNG  = 400      # cm
ALPHA    = 0.3      # EMA smoothing
POLL_GAP = 0.055    # 55ms between groups (cross-talk guard)

# Opposing sensors → fire in parallel (can't hear each other)
PARALLEL_GROUPS = [
    ('FC', 'BK'),   # front ↔ back
    ('FL', 'R'),    # front-left ↔ right
    ('FR', 'L'),    # front-right ↔ left
]

console = Console()

# ── Sensor I/O ────────────────────────────────────────────

def safe_read(sensor, retries=3):
    """Read with retry cap. Returns cm or -1."""
    for _ in range(retries):
        try:
            d = sensor._get_distance()
            if d is not None and 2 < d < MAX_RNG:
                return d
        except Exception:
            pass
    return -1


def poll_parallel(probes):
    """Fire opposing sensors simultaneously. 3 groups × 55ms ≈ 165ms total."""
    readings = {}
    for group in PARALLEL_GROUPS:
        results = {}
        threads = []
        for key in group:
            if key not in probes:
                continue
            def _read(k=key):
                results[k] = safe_read(probes[k])
            t = threading.Thread(target=_read)
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=1.0)
        readings.update(results)
        time.sleep(POLL_GAP)
    return readings


# ── Style helpers ─────────────────────────────────────────

def zone_style(cm):
    if cm < 0:       return "dim"
    if cm < DANGER:  return "bold red"
    if cm < CAUTION: return "yellow"
    return "green"


def zone_label(cm):
    if cm < 0:       return "ERR"
    if cm < DANGER:  return "DANGER"
    if cm < CAUTION: return "WARN"
    return "CLEAR"


def proximity_bar(cm, width=26):
    """Longer bar = closer obstacle (proximity indicator)."""
    if cm < 0:
        return Text(" ? ", style="dim")
    # Invert: closer → longer bar
    prox = max(0, MAX_RNG - cm)
    length = max(0, round(prox / MAX_RNG * width))
    if length == 0:
        return Text("·", style="dim")
    style = zone_style(cm)
    return Text("█" * length, style=style)


# ── Dashboard builder ─────────────────────────────────────

def _add_sensor(t, key, cm):
    """Append a 9-visible-char sensor label to a Text object."""
    d = f"{cm:4.0f}cm" if cm > 0 else "   ERR"  # always 6 chars
    t.append(f"{key:>2} {d}", style=zone_style(cm))   # 2+1+6 = 9 chars


def build_alert(sm):
    """Alert banner panel."""
    has_danger  = any(0 < v < DANGER  for v in sm.values())
    has_caution = any(DANGER <= v < CAUTION for v in sm.values())

    if has_danger:
        return Text("  !! OBSTACLE DETECTED !!  ", style="bold white on red", justify="center")
    elif has_caution:
        return Text("  >> CAUTION — OBJECTS NEARBY <<  ", style="bold on yellow", justify="center")
    else:
        return Text("  ALL CLEAR  ", style="bold on green", justify="center")


def build_radar(sm):
    """Bird's-eye radar view built with Text.append() — no markup escaping issues."""
    fc = sm.get('FC', -1); fl = sm.get('FL', -1); fr = sm.get('FR', -1)
    lf = sm.get('L',  -1); rt = sm.get('R',  -1); bk = sm.get('BK', -1)

    #   Col layout (visible chars):
    #     Front:  FL@6  FC@22  FR@38   (9-char sensors, 7-char gaps)
    #     Middle: 2 + L(9) + conn(8) + box(14) + conn(8) + R(9) = 50
    #     Box starts at col 19, center at col 26
    #     Back:   BK@22  (centered under FC / robot)

    lines = []

    # ── Front sensors ──
    t = Text()
    t.append(" " * 6)
    _add_sensor(t, "FL", fl)
    t.append(" " * 7)
    _add_sensor(t, "FC", fc)
    t.append(" " * 7)
    _add_sensor(t, "FR", fr)
    lines.append(t)

    lines.append(Text())

    # ── Diagonal 1 (wide) ──
    #   \ at col 14, | at col 26, / at col 38
    t = Text()
    t.append("              \\           |           /", style="dim")
    lines.append(t)

    # ── Diagonal 2 (narrow) ──
    #   \ at col 17, | at col 26, / at col 35
    t = Text()
    t.append("                 \\        |        /", style="dim")
    lines.append(t)

    lines.append(Text())

    # ── Middle row: L ────── [ROBOT] ────── R ──
    t = Text()
    t.append(" " * 2)
    _add_sensor(t, "L", lf)               # cols 2-10  (9 chars)
    t.append(" ────── ", style="dim")      # cols 11-18 (8 chars)
    t.append("╭────────────╮", style="cyan")  # cols 19-32 (14 chars)
    t.append(" ────── ", style="dim")      # cols 33-40 (8 chars)
    _add_sensor(t, "R", rt)               # cols 41-49 (9 chars)
    lines.append(t)

    # ── Robot body (starts at col 19 to match box) ──
    t = Text()
    t.append(" " * 19)
    t.append("│", style="cyan")
    t.append("  TURTLEBOT ", style="bold white")  # 12 chars inner
    t.append("│", style="cyan")
    lines.append(t)

    # ── Robot bottom ──
    t = Text()
    t.append(" " * 19)
    t.append("╰────────────╯", style="cyan")
    lines.append(t)

    lines.append(Text())

    # ── Diagonal 3 (narrow) ──
    t = Text()
    t.append("                 /        |        \\", style="dim")
    lines.append(t)

    # ── Diagonal 4 (wide) ──
    t = Text()
    t.append("              /           |           \\", style="dim")
    lines.append(t)

    lines.append(Text())

    # ── Back sensor (col 22, centered under robot) ──
    t = Text()
    t.append(" " * 22)
    _add_sensor(t, "BK", bk)
    lines.append(t)

    # Combine all lines into one Text
    result = Text()
    for i, line in enumerate(lines):
        result.append_text(line)
        if i < len(lines) - 1:
            result.append("\n")

    return Panel(
        result,
        title="[bold]Radar View[/bold]",
        border_style="dim cyan",
        padding=(1, 2),
    )


def build_table(sm, raw):
    """Sensor detail table, sorted by distance (closest-first)."""
    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold white",
        border_style="dim cyan",
        expand=True,
        padding=(0, 1),
    )
    table.add_column("Sensor",    style="white",  min_width=15)
    table.add_column("Dist",      justify="right", min_width=8)
    table.add_column("Proximity", min_width=28)
    table.add_column("Raw",       justify="right", style="dim", min_width=6)
    table.add_column("Zone",      min_width=7)

    # Sort: closest first, errors last
    sensor_map = {s[0]: s for s in SENSORS}
    sorted_keys = sorted(
        [k for k in sm],
        key=lambda k: sm[k] if sm[k] > 0 else 9999,
    )

    for key in sorted_keys:
        info = sensor_map.get(key)
        if not info:
            continue
        _, pin, label_text = info
        sv = sm[key]
        rv = raw.get(key, -1)
        style = zone_style(sv)

        table.add_row(
            Text(f"{key:>2} {label_text}", style="white"),
            Text(f"{sv:.0f}cm" if sv > 0 else "ERR", style=style),
            proximity_bar(sv),
            Text(f"{rv:.0f}" if rv > 0 else "—"),
            Text(zone_label(sv), style=style),
        )

    return table


def build_footer(sm, hz):
    """Footer line with nearest sensor + legend + refresh rate."""
    valid = {k: v for k, v in sm.items() if v > 0}
    if valid:
        nk = min(valid, key=valid.get)
        nd = valid[nk]
        nl = next((s[2] for s in SENSORS if s[0] == nk), nk)
    else:
        nd, nl = -1, "NONE"

    t = Text()
    t.append("  Nearest: ", style="dim")
    if nd > 0:
        t.append(f"{nd:.0f}cm {nl}", style=zone_style(nd))
    else:
        t.append("—", style="dim")
    t.append("      ")
    t.append("■", style="bold red");    t.append(f" <{DANGER}cm  ")
    t.append("■", style="bold yellow"); t.append(f" <{CAUTION}cm  ")
    t.append("■", style="bold green");  t.append(f" >{CAUTION}cm")
    t.append(f"      {hz:.1f} Hz", style="dim")
    return t


def build_display(sm, raw, hz):
    """Assemble the full dashboard."""
    return Panel(
        Group(
            build_alert(sm),
            Text(""),
            build_radar(sm),
            build_table(sm, raw),
            Text(""),
            build_footer(sm, hz),
        ),
        title="[bold cyan] TURTLEBOT ULTRASONIC RADAR [/bold cyan]",
        subtitle="[dim]Ctrl+C to quit[/dim]",
        border_style="cyan",
        padding=(0, 1),
    )


# ── Diagnostics ───────────────────────────────────────────

def run_diagnostics(probes):
    """Verbose per-sensor test."""
    console.print()
    console.rule("[bold]SENSOR DIAGNOSTICS[/bold]")
    console.print()

    try:
        import RPi.GPIO as G
        console.print(f"  RPi.GPIO [bold]{G.VERSION}[/bold]  mode={G.getmode()}")
    except Exception:
        pass

    working = 0
    for key, pin, label in SENSORS:
        sensor = probes.get(key)
        if sensor is None:
            console.print(f"  [red]✗[/red] {key:>2} {label:<14} D{pin} — init failed")
            continue

        console.print(f"  Testing [bold]{key:>2} {label:<14}[/bold] D{pin} ...")

        results = []
        for i in range(3):
            d = safe_read(sensor, retries=3)
            tag = f"[green]{d:.0f}cm[/green]" if d > 0 else "[red]FAIL[/red]"
            console.print(f"    read {i+1}: {tag}")
            results.append(d)
            time.sleep(0.1)

        good = [r for r in results if r > 0]
        if good:
            console.print(f"    [green]OK[/green] — avg {sum(good)/len(good):.0f}cm")
            working += 1
        else:
            console.print(f"    [red]ALL READS FAILED[/red]")
            console.print(f"    [yellow]→ Check wiring to D{pin}, power (5V/3.3V), connections[/yellow]")
        console.print()

    console.rule(f"[bold]{working}/{len(SENSORS)} sensors responding[/bold]")
    console.print()
    return working


# ── Main ──────────────────────────────────────────────────

def main():
    diag_only = "--diag" in sys.argv

    console.print("[bold]Initializing sensors...[/bold]")
    probes = {}
    for key, pin, label in SENSORS:
        try:
            probes[key] = GroveUltrasonicRanger(pin)
            console.print(f"  [green]✓[/green] {key} {label} (D{pin})")
        except Exception as e:
            console.print(f"  [red]✗[/red] {key} {label} (D{pin}): {e}")

    if not probes:
        console.print("[red]No sensors initialized![/red]")
        sys.exit(1)

    if diag_only:
        run_diagnostics(probes)
        return

    # Quick sanity check (1 read per sensor)
    console.print("\n[dim]Quick sensor check...[/dim]")
    ok = 0
    for key, sensor in probes.items():
        d = safe_read(sensor, retries=2)
        status = f"[green]{d:.0f}cm[/green]" if d > 0 else "[red]no response[/red]"
        console.print(f"  {key}: {status}")
        if d > 0:
            ok += 1
    if ok == 0:
        console.print("[yellow]No sensors responding. Run with --diag for details.[/yellow]")
        console.print("[dim]Starting radar anyway...[/dim]")
    console.print()

    smoothed = {}
    prev_t = time.time()
    hz = 0.0

    try:
        with Live(console=console, refresh_per_second=8, screen=True) as live:
            while True:
                raw = poll_parallel(probes)

                # EMA smooth (hold last good value on transient errors)
                for key, val in raw.items():
                    if val > 0:
                        if key in smoothed and smoothed[key] > 0:
                            smoothed[key] = ALPHA * val + (1 - ALPHA) * smoothed[key]
                        else:
                            smoothed[key] = val
                    elif key not in smoothed:
                        smoothed[key] = -1

                now = time.time()
                dt = now - prev_t
                if dt > 0:
                    hz = 0.5 / dt + 0.5 * hz
                prev_t = now

                live.update(build_display(smoothed, raw, hz))

    except KeyboardInterrupt:
        pass

    console.print("\n[bold]Radar stopped.[/bold]")


if __name__ == '__main__':
    main()
