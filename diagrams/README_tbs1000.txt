TBS1000C and TBS1000 hook-up diagrams (supplied as PNGs in this folder; none are supplied yet)

Name:      hook_tbs1000c_<5560A|5522A>_<GROUP>.png      TBS1000C   (5520A uses the 5522A picture)
           hook_tbs1000_<5560A|5522A>_<GROUP>.png       TBS1000 (non-C)
Fallback:  hook_tbs1000c_<GROUP>.png / hook_tbs1000_<GROUP>.png
GROUP:     DCV      calibrator SCOPE volts -> CHn, 1 MOhm (DC gain)
           LEVSINE  calibrator SCOPE leveled sine -> CHn through 50 Ohm feedthrough (bandwidth, edge trigger)
           MARKER   calibrator SCOPE time marker -> CH1 through 50 Ohm feedthrough (sample rate / delay time)
           EXTTRIG  calibrator -> power splitter -> CH1 and AUX IN (TBS1000C, figure p. 29) / EXT TRIG (TBS1000, figure p. 4-9),
                    50 Ohm feedthrough on each
A missing picture is not an error: the prompt shows the text steps (the TDS2000C wording) and says which file name it looked for.
No front-panel photo of either scope was supplied.
