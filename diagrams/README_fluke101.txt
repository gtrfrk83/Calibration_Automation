Fluke 101 hook-up diagrams (owner supplies the PNGs; none were drawn here)

The 101 has two jacks (Users Manual, Terminals, printed p. 3): COM and the input jack printed 'VΩ'.  Every point uses the same two leads (group VOHM):

    hook_fluke101_5560A_VOHM.png      Fluke 5560A  OUTPUT V/Ω HI -> meter VΩ (red),  OUTPUT V/Ω LO -> meter COM (black)
    hook_fluke101_5522A_VOHM.png      Fluke 5522A  NORMAL HI -> meter VΩ (red),  NORMAL LO -> meter COM (black)

Until they exist the readiness check (python tools/readiness_check.py Fluke_101_Verification) lists them as missing; the text hook-up prompt is shown meanwhile.
The meter has no current jack, so there are no UAMP / AMP10 pictures.
