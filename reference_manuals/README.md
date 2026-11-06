# Reference manuals (not shipped)

Manufacturer manuals that procedures and drivers were written from. They are kept in the repository so they can be read when a procedure or
driver is built or checked, but they are **not part of a build**: `.gitattributes` marks this folder `export-ignore`, so `git archive` (the
build command) and GitHub "Download ZIP" leave it out.

This is not the suite's own manual viewer folder. The app looks for operator manuals in `manuals/` (see `manuals.py`); nothing here is shown in the app.

Add a new manual here under its original file name. Code comments and NOTES.md cite manuals by file name only, so moving them into this folder does not change any reference.

| File | Manual | Used by |
|---|---|---|
| `96000__rpmeng0100.pdf` | Fluke 96000 Series Remote Programmers Manual | `drivers/reference_instruments.py` (96270A FM / AM / frequency counter commands) |
| `SMA100B_UserManual_en_14.pdf` | R&S SMA100B User Manual 1178.3834.02-14 | `drivers/rs_sma100b.py`, 53220A family SMA100B source |
