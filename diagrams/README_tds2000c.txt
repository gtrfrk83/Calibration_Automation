TDS2000C / TDS1000C-EDU hook-up diagrams (supplied as PNGs in this folder)

Name:      hook_tds2000c_<5560A|5522A>_<GROUP>.png      (5520A uses the 5522A picture)
Fallback:  hook_tds2000c_<GROUP>.png
GROUP:     DCV      calibrator SCOPE volts -> CHn, 1 MOhm (DC gain, vertical position)
           LEVSINE  calibrator SCOPE leveled sine -> CHn through 50 Ohm feedthrough (bandwidth, edge trigger)
           MARKER   calibrator SCOPE time marker -> CH1 through 50 Ohm feedthrough (sample rate / delay time)
           EXTTRIG  calibrator -> power splitter -> CH1 and EXT TRIG, 50 Ohm feedthrough on each (external trigger, manual p. 4-9)
A missing picture is not an error: the prompt shows the text steps and says which file name it looked for.
