#!/usr/bin/env python3
import ev3dev.ev3 as ev3
from time import sleep

print("Connecting...")

column_port = 'outA'
column_direction = 1
column_speed = 200
column_pos_top = 200
column_pos_bottom = -200

spirals_port = 'outB'
spirals_direction = -1
spirals_speed = 720
spirals_abs_pos = 0

def run_column(pos):
    column.run_to_abs_pos(speed_sp = column_speed, position_sp = (column_direction * pos))

def run_spirals(cone_no):
    spirals.run_to_abs_pos(speed_sp = spirals_speed, position_sp = (spirals_abs_pos + spirals_direction * cone_no * 180))

column = ev3.LargeMotor(column_port)
spirals = ev3.LargeMotor(spirals_port)

print("Ready!")

cones = 0
cmd = ""
while cmd != "q":
    cmd = input()

    if cmd == "p":
        cones += 1
        run_column(column_pos_bottom)
        sleep(5)
        run_spirals(cones)
        run_column(column_pos_top)
    if cmd == "d":
        cones -= 1
        if cones < 0:
            cones = 0
        else:
            run_spirals(cones)
    if cmd == "a":
        cones = 0
        run_spirals(cones)

    print("Cones:", cones)
