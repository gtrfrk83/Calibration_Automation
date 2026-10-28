Hook-up diagrams for the Fluke 6060A / 6060A-AF performance verification (supplied by Mike as PNGs in this folder; none has been drawn).

The procedure looks for:
    diagrams/hook_6060A_<GROUP>.png
When no file is found the hook-up prompt shows the written steps and names the file it expected. A missing picture never stops a run.

GROUP names (one picture per wiring group; the prompt is shown again whenever the group changes):
    POWERON   4A-3: no connections (switch the 6060A off and on); a picture is optional
    RX        6060A RF OUTPUT to the 8902A RF INPUT, 6060A rear 10 MHz IN/OUT to the 8902A rear 10 MHz reference input
              (4A-4 synthesis, 4A-7 and the lower levels of 4A-8, modulation tests 1, 2, 4, 5, 7 and 8)
    RXPWR     6060A RF OUTPUT to the 11722A power sensor module on the 8902A (4A-8, levels of -19 dBm and above, RF power)
    PM        6060A RF OUTPUT to the R&S NRP40T sensor on the 96270A in power-meter mode (4A-5 high level, 4A-6 mid level)
    SA        6060A RF OUTPUT to the HP 8563E RF INPUT (4A-11 harmonics and spurs)
    EXT1K     as RX plus the LF function generator (1 kHz, 0.7071 V rms) through a BNC T to the 6060A MOD INPUT and a DVM (test 3, external AM)
    EXT10K    as EXT1K at 10 kHz (test 6, external FM, 245 to 1045 MHz upwards)
    EXT400    as EXT1K at 0.4 kHz (test 6, external FM, 1045 down to 245 MHz and the 9.99 / 0.999 kHz deviation points)

Calibration prompts (no picture is looked up for these): 8902A RF power (11722A on the 8902A calibration output), 8902A AM and 8902A FM (the 8902A calibration source to its RF INPUT).
