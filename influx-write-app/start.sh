#!/bin/bash

python vibration-influx-write.py &
python energy-influx-write.py &

wait
