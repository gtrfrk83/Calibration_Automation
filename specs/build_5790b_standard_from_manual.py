"""Builds specs/standards/fluke_5790b_standard.json from the Fluke 5790B Operators Manual, Chapter 1 (Electrical Specifications).

    python specs/build_5790b_standard_from_manual.py            # writes specs/standards/fluke_5790b_standard.json

Every number below was transcribed by eye from RENDERED PAGE IMAGES (pdftoppm -r 110) of '5790B Manual.pdf', not from extracted
text.  Page numbers: the printed manual page is 1-N; the PDF page is N + 10 (1-9 is PDF page 19).  Rows carry the PDF page in 'page';
notes and problems quote the printed page.  Values are SI base units (V, Hz); ppm / percent of reading become 'rel', microvolts become 'abs'.
Nothing is guessed: ambiguities are written to 'problems'.

Tables loaded (printed pages):
  1-9..1-11   Absolute AC Voltage (90 d / 1 yr / 2 yr, ppm of reading + uV) and the AC/DC Transfer Mode column (2 yr, ppm)
  1-12..1-13  Relative AC Voltage (same layout)
  1-14        Absolute AC Non-sine Voltage (1 yr, % of reading + uV)
  1-15        Absolute and Relative DC Voltage
  1-16..1-18  AC secondary: 24 Hour AC Stability (slow filter, +/-1 degC)
  1-20..1-22  Absolute Wideband (5790B/3, /5, /AF): absolute accuracy and flatness; 5790B/AF 50 MHz specification
Not loaded (the schema has no field): temperature coefficients, input resistance (1-16..1-18), flatness temperature coefficient (1-20..1-22),
resolution tables (1-9, 1-20..1-22), frequency measurement accuracy (1-19, '100 ppm + digits'), reading rates and settling times.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import specmanager as sm  # noqa: E402

PDF_OFFSET = 10      # printed page 1-N  ->  PDF page N + 10
MV, V_ = 1e-3, 1.0

# ---------------------------------------------------------------------------------------------------------- bands
AC_BANDS = [(10, 20), (20, 40), (40, 20e3), (20e3, 50e3), (50e3, 100e3), (100e3, 300e3), (300e3, 500e3), (500e3, 1e6)]
NS_BANDS = [(10, 45), (45, 1e3), (1e3, 20e3), (20e3, 100e3)]
WB_BANDS = [(10, 30), (30, 120), (120, 1.2e3), (1.2e3, 120e3), (120e3, 500e3), (500e3, 1.2e6), (1.2e6, 2e6), (2e6, 10e6),
            (10e6, 20e6), (20e6, 30e6), (30e6, 50e6)]
RANGES = [('2.2 mV', 2.2e-3), ('7 mV', 7e-3), ('22 mV', 22e-3), ('70 mV', 70e-3), ('220 mV', 220e-3), ('700 mV', 700e-3), ('2.2 V', 2.2),
          ('7 V', 7.0), ('22 V', 22.0), ('70 V', 70.0), ('220 V', 220.0), ('700 V', 700.0), ('1000 V', 1000.0)]
TOP = dict(RANGES)


def fmt_hz(f):
    for div, u in ((1e6, 'MHz'), (1e3, 'kHz'), (1, 'Hz')):
        if f >= div:
            return f'{f / div:g} {u}'


# ---------------------------------------------------------------------------------------------------------- notes (ids are file-wide)
NOTES = {
    1: 'Absolute AC, 70 mV / 220 mV / 700 mV, 10 Hz to 20 Hz (printed p.1-10 marker [1]): for 9.5 to 10 Hz the specification is +/-(1000 ppm of reading + 1.5 uV) (footnote on p.1-11).',
    2: 'Absolute AC, 2.2 V / 7 V / 22 V / 70 V, 10 Hz to 20 Hz (markers [2] on pp.1-10, 1-11): for 9.5 to 10 Hz the specification is +/-(1000 ppm of reading) (footnote on p.1-11).',
    3: 'Range marked [3] (absolute, p.1-11) / [1] (relative, p.1-13): inputs >100 kHz and with a V*Hz product >2.2E7 are TYPICAL.',
    4: 'Marked [4] (absolute, p.1-11) / [2] (relative, p.1-13): typical specification, as determined by sourcing with the Fluke 5205A Precision Power Amplifier.',
    5: 'Marked [5] (absolute, p.1-11) / [3] (relative, p.1-13): inputs >30 kHz and >750 V are TYPICAL, as determined by sourcing with the Fluke 5205A.',
    6: 'p.1-11 note: the product is to be used in controlled environments; for disturbances on the mains supply of >0.5 Vrms from 10 MHz to 40 MHz, add 5 ppm to the 2.2 V range.',
    7: 'Specifications are at a 99 % confidence level, k = 2.58, normally distributed, valid after 30 minutes warm-up or twice the time the product has been off (p.1-9). Temperature: +/-5 degC of calibration temperature (pp.1-10 to 1-13).',
    8: 'Non-sine (p.1-14 footnote [1]): specifications apply for non-sinusoidal inputs with crest factor <3.0 and harmonic content band-limited to <1 MHz.',
    9: 'Non-sine (p.1-14 footnote [2]): crest factor limited to <2.3 for signals greater than 75 % of full-scale RMS (2.2 V and 22 V ranges).',
    10: 'DC (p.1-15 note): specification valid only when the dc input signal is averaged with an equal and opposite dc input signal to eliminate dc offset errors; use of Input 1 for dc is not recommended (thermal EMFs in the N connector).',
    11: 'AC/DC Transfer Mode column (pp.1-10 to 1-13): printed as "AC/DC Transfer Mode +/- ppm, 2 Years" with no further definition; stored as ppm of reading, 2 yr only.',
    12: 'Wideband (p.1-22 footnote [1]): range limits same as INPUT 1 or INPUT 2.',
    13: 'Wideband flatness (p.1-22 footnote [2]): relative to 1 kHz, 1 year, +/-3 degC; for the 2-year specification multiply by 1.5 (not applied here: no 2 yr value is stored).',
    14: 'Wideband (p.1-22 footnote [4]): wideband absolute specification is 0 degC to 50 degC at the input connector.',
    15: 'Wideband (p.1-22 footnote [5]): 30 MHz - 50 MHz applies to 5790B/5 and 5790B/AF only.',
    16: 'Wideband (p.1-22 footnote [6]): on the 7 V range the maximum amplitude is limited to 3.5 V at 30 MHz - 50 MHz.',
    17: 'Secondary specification (pp.1-16 to 1-18): 24 hour ac stability, +/-1 degC, slow filter. 2.2 mV / 7 mV / 22 mV ranges are PEAK-TO-PEAK microvolts; 70 mV and above are ppm of reading (p.1-16 row separator "+/- (ppm of Reading)"). Not an accuracy specification.',
    18: 'p.1-18 secondary footnote [3]: 70 V / 220 V ranges: inputs with a V*Hz product >2.2E7 are unspecified.',
    19: 'p.1-18 secondary footnote [4]/[5]: 700 V and 1000 V rows marked typical, as determined by sourcing with the Fluke 5205A (10 Hz - 20 Hz; 1000 V also >30 kHz and >750 V).',
    20: '5790B/AF only (p.1-22): absolute specification is +/-0.23 % of voltage reading (1 year, 23 degC +/-3 degC, 95 % confidence, k=2, normally distributed) at 50 MHz, 223.61 mV, referenced to the end of the provided serialized 0.91 m (3 ft) cable; with the cable and 50 MHz Cable Correction the product is only specified within +/-4 % of 50 MHz, 223.61 mV (214.66 mV to 232.55 mV).',
}

# ---------------------------------------------------------------------------------------------------------- data (printed pages in comments)
# one string per frequency band: "90d 1yr 2yr" where each is "ppm+uV" or "ppm" (the manual prints no uV term from 2.2 V up)
ABS_AC = {   # printed pp.1-9 (2.2 mV - 22 mV), 1-10 (70 mV - 22 V), 1-11 (70 V - 1000 V)
    '2.2 mV': ['1700+1.3 1700+1.3 1700+1.3', '740+1.3 740+1.3 740+1.3', '420+1.3 420+1.3 420+1.3', '810+2.0 810+2.0 820+2.0',
               '1200+2.5 1200+2.5 1200+2.5', '2300+4.0 2300+4.0 2300+4.0', '2400+6.0 2400+8.0 2600+8.0', '3200+6.0 3500+8.0 5000+8.0'],
    '7 mV': ['850+1.3 850+1.3 850+1.3', '370+1.3 370+1.3 370+1.3', '210+1.3 210+1.3 210+1.3', '400+2.0 400+2.0 410+2.0',
             '600+2.5 600+2.5 610+2.5', '1200+4.0 1200+4.0 1200+4.0', '1300+6.0 1300+8.0 1400+8.0', '2000+6.0 2300+8.0 3600+8.0'],
    '22 mV': ['290+1.3 290+1.3 290+1.3', '180+1.3 190+1.3 190+1.3', '110+1.3 110+1.3 110+1.3', '210+2.0 210+2.0 210+2.0',
              '310+2.5 310+2.5 310+2.5', '810+4.0 810+4.0 820+4.0', '860+6.0 890+8.0 1000+8.0', '1400+6.0 1700+8.0 2600+8.0'],
    '70 mV': ['240+1.5 240+1.5 240+1.5', '120+1.5 120+1.5 130+1.5', '64+1.5 65+1.5 69+1.5', '120+2.0 130+2.0 130+2.0',
              '260+2.5 260+2.5 260+2.5', '510+4.0 510+4.0 530+4.0', '660+6.0 670+8.0 680+8.0', '1100+6.0 1100+8.0 1300+8.0'],
    '220 mV': ['210+1.5 210+1.5 210+1.5', '84+1.5 85+1.5 87+1.5', '37+1.5 38+1.5 43+1.5', '69+2.0 69+2.0 73+2.0',
               '160+2.5 160+2.5 160+2.5', '240+4.0 250+4.0 280+4.0', '360+6.0 380+8.0 400+8.0', '940+6.0 1000+8.0 1200+8.0'],
    '700 mV': ['210+1.5 210+1.5 210+1.5', '75+1.5 76+1.5 78+1.5', '31+1.5 33+1.5 38+1.5', '50+2.0 51+2.0 56+2.0',
               '79+2.5 79+2.5 84+2.5', '160+4.0 180+4.0 210+4.0', '300+6.0 300+8.0 340+8.0', '900+6.0 960+8.0 1200+8.0'],
    '2.2 V': ['200 200 200', '65 66 69', '22 24 29', '45 46 52', '70 71 76', '150 160 200', '250 260 310', '840 900 1200'],
    '7 V': ['200 200 200', '66 67 70', '22 24 29', '46 48 53', '80 81 88', '180 190 220', '380 400 470', '1100 1200 1500'],
    '22 V': ['200 200 200', '66 67 70', '25 27 31', '46 48 53', '80 81 85', '180 190 220', '380 400 470', '1100 1200 1500'],
    '70 V': ['200 200 200', '67 68 72', '30 32 39', '56 57 63', '91 94 110', '190 200 220', '400 410 510', '1100 1200 1500'],
    '220 V': ['200 200 200', '67 68 72', '29 31 38', '67 69 77', '96 98 110', '210 210 260', '440 500 700'],
    '700 V': ['200 200 200', '96 99 110', '39 41 47', '120 130 150', '400 500 850'],
    '1000 V': ['200 200 200', '96 99 110', '37 38 44', '120 130 150', '400 500 850'],
}
ABS_AC_PAGE = {'2.2 mV': 9, '7 mV': 9, '22 mV': 9, '70 mV': 10, '220 mV': 10, '700 mV': 10, '2.2 V': 10, '7 V': 10, '22 V': 10,
               '70 V': 11, '220 V': 11, '700 V': 11, '1000 V': 11}
# AC/DC transfer mode ppm, 2 years, bands 1-4 only (printed pp.1-10, 1-11)
ABS_TRANSFER = {'220 mV': [210, 82, 34, 67], '700 mV': [210, 73, 27, 47], '2.2 V': [200, 63, 18, 43], '7 V': [200, 63, 18, 44],
                '22 V': [200, 63, 21, 44], '70 V': [200, 63, 25, 55], '220 V': [200, 63, 23, 63], '700 V': [200, 92, 36], '1000 V': [200, 92, 33]}
ABS_NOTES = {   # (range, band index) -> note ids
    **{(r, 0): [1] for r in ('70 mV', '220 mV', '700 mV')}, **{(r, 0): [2] for r in ('2.2 V', '7 V', '22 V', '70 V')},
    **{('70 V', i): [3] for i in range(1, 8)}, **{('220 V', i): [3] for i in range(1, 7)},
    ('70 V', 0): [2, 3], ('220 V', 0): [3], ('700 V', 0): [4], ('1000 V', 0): [4], ('1000 V', 3): [5], ('1000 V', 4): [5]}

REL_AC = {   # printed pp.1-12 (2.2 mV - 700 mV), 1-13 (2.2 V - 1000 V)
    '2.2 mV': ['100+1.3 110+1.3 110+1.3', '54+1.3 64+1.3 68+1.3', '44+1.3 57+1.3 61+1.3', '57+2.0 67+2.0 110+2.0', '79+2.5 86+2.5 120+2.5',
               '190+4.0 230+4.0 390+4.0', '590+6.0 720+8.0 1200+8.0', '2200+6.0 2600+8.0 4400+8.0'],
    '7 mV': ['80+1.3 83+1.3 86+1.3', '33+1.3 39+1.3 45+1.3', '29+1.3 36+1.3 42+1.3', '40+2.0 44+2.0 63+2.0', '53+2.5 57+2.5 72+2.5',
             '110+4.0 130+4.0 210+4.0', '370+6.0 450+8.0 740+8.0', '1600+6.0 2000+8.0 3400+8.0'],
    '22 mV': ['69+1.3 72+1.3 75+1.3', '34+1.3 40+1.3 46+1.3', '30+1.3 36+1.3 43+1.3', '40+2.0 45+2.0 64+2.0', '53+2.5 57+2.5 73+2.5',
              '97+4.0 110+4.0 160+4.0', '310+6.0 380+8.0 610+8.0', '1200+6.0 1500+8.0 2500+8.0'],
    '70 mV': ['60+1.5 61+1.5 62+1.5', '27+1.5 30+1.5 37+1.5', '22+1.5 25+1.5 34+1.5', '34+2.0 36+2.0 44+2.0', '53+2.5 54+2.5 62+2.5',
              '110+4.0 120+4.0 170+4.0', '270+6.0 290+8.0 320+8.0', '910+6.0 970+8.0 1200+8.0'],
    '220 mV': ['60+1.5 61+1.5 62+1.5', '27+1.5 29+1.5 35+1.5', '22+1.5 24+1.5 31+1.5', '22+2.0 24+2.0 33+2.0', '51+2.5 52+2.5 59+2.5',
               '100+4.0 120+4.0 170+4.0', '260+6.0 290+8.0 310+8.0', '890+6.0 950+8.0 1200+8.0'],
    '700 mV': ['60+1.5 61+1.5 62+1.5', '27+1.5 29+1.5 34+1.5', '22+1.5 24+1.5 31+1.5', '22+2.0 24+2.0 33+2.0', '51+2.5 52+2.5 59+2.5',
               '100+4.0 120+4.0 170+4.0', '260+6.0 270+8.0 310+8.0', '890+6.0 950+8.0 1200+8.0'],
    '2.2 V': ['60 61 62', '26 28 34', '20 22 27', '21 23 33', '49 50 57', '92 110 160', '220 230 280', '830 890 1200'],
    '7 V': ['60 61 62', '27 29 36', '20 22 27', '23 26 35', '62 64 73', '140 150 180', '360 380 450', '1100 1200 1500'],
    '22 V': ['60 61 62', '28 30 37', '20 22 27', '23 26 35', '62 64 69', '140 150 180', '360 380 450', '1100 1200 1500'],
    '70 V': ['60 62 63', '29 31 39', '23 25 34', '25 27 39', '64 68 85', '140 150 180', '370 390 490', '1100 1200 1500'],
    '220 V': ['61 62 64', '30 32 40', '23 25 34', '30 34 49', '66 69 83', '160 170 220', '410 480 680'],
    '700 V': ['62 63 65', '31 33 41', '24 25 31', '100 110 140', '390 500 850'],
    '1000 V': ['62 63 65', '31 33 41', '24 25 31', '100 110 140', '390 500 850'],
}
REL_AC_PAGE = {'2.2 mV': 12, '7 mV': 12, '22 mV': 12, '70 mV': 12, '220 mV': 12, '700 mV': 12, '2.2 V': 13, '7 V': 13, '22 V': 13,
               '70 V': 13, '220 V': 13, '700 V': 13, '1000 V': 13}
REL_TRANSFER = {'220 mV': [55, 20, 17, 17], '700 mV': [55, 20, 15, 15], '2.2 V': [55, 19, 15, 15], '7 V': [55, 19, 15, 18],
                '22 V': [55, 19, 15, 18], '70 V': [55, 19, 15, 22], '220 V': [55, 19, 15, 24], '700 V': [55, 19, 19], '1000 V': [55, 19, 19]}
REL_NOTES = {**{('70 V', i): [3] for i in range(8)}, **{('220 V', i): [3] for i in range(7)}, ('700 V', 0): [4], ('1000 V', 0): [4],
             ('1000 V', 3): [5], ('1000 V', 4): [5]}

# Non-sine, 1 year only, "% of reading + uV" (p.1-14); V ranges print the percent only
NONSINE = {
    '2.2 mV': ['0.1+1.3', '0.1+1.3', '0.17+1.3', '0.5+2.5'], '7 mV': ['0.1+1.3', '0.1+1.3', '0.17+1.3', '0.5+2.5'],
    '22 mV': ['0.1+1.3', '0.1+1.3', '0.17+1.3', '0.5+2.5'], '70 mV': ['0.1+1.5', '0.1+1.5', '0.17+1.5', '0.5+2.5'],
    '220 mV': ['0.1+1.5', '0.1+1.5', '0.17+1.5', '0.5+2.5'], '700 mV': ['0.1+1.5', '0.1+1.5', '0.17+1.5', '0.5+2.5'],
    '2.2 V': ['0.1', '0.1', '0.17', '0.5'], '7 V': ['0.1', '0.1', '0.17', '0.5'], '22 V': ['0.1', '0.1', '0.17', '0.5'],
    '70 V': ['0.1', '0.1', '0.17', '0.5'],
}

# DC (p.1-15), "90d 1yr 2yr", ppm of reading + uV
ABS_DC = {'220 mV': '37+1.5 38+1.5 43+1.5', '700 mV': '31+1.5 33+1.5 38+1.5', '2.2 V': '22 24 29', '7 V': '22 24 29', '22 V': '25 27 31',
          '70 V': '30 32 39', '220 V': '29 31 38', '700 V': '39 41 47', '1000 V': '37 38 44'}
REL_DC = {'220 mV': '22+1.5 24+1.5 31+1.5', '700 mV': '22+1.5 24+1.5 31+1.5', '2.2 V': '20 22 27', '7 V': '20 22 27', '22 V': '20 22 27',
          '70 V': '23 25 34', '220 V': '23 25 34', '700 V': '24 25 31', '1000 V': '24 25 31'}

# 24 hour AC stability (pp.1-16 .. 1-18): uV peak-to-peak up to 22 mV, ppm of reading from 70 mV
STAB24 = {
    '2.2 mV': [0.4, 0.4, 0.4, 0.4, 0.8, 1.5, 3.0, 4.5], '7 mV': [0.4, 0.4, 0.4, 0.4, 0.8, 1.5, 3.0, 4.5], '22 mV': [0.4, 0.4, 0.4, 0.4, 0.8, 1.5, 3.0, 4.5],
    '70 mV': [18, 18, 18, 18, 24, 24, 48, 150], '220 mV': [12, 8, 8, 8, 18, 24, 36, 120], '700 mV': [8, 6, 6, 6, 12, 18, 36, 96],
    '2.2 V': [8, 5, 5, 5, 10, 18, 30, 90], '7 V': [8, 5, 5, 5, 10, 18, 30, 90], '22 V': [8, 5, 5, 5, 10, 18, 30, 90],
    '70 V': [8, 5, 5, 5, 18, 36, 48, 120], '220 V': [8, 5, 5, 5, 18, 36, 48], '700 V': [8, 5, 5, 18, 36], '1000 V': [8, 5, 5, 18, 36],
}
STAB_PAGE = {'2.2 mV': 16, '7 mV': 16, '22 mV': 16, '70 mV': 16, '220 mV': 16, '700 mV': 17, '2.2 V': 17, '7 V': 17, '22 V': 17, '70 V': 17,
             '220 V': 18, '700 V': 18, '1000 V': 18}
STAB_NOTES = {('70 V', i): [18] for i in range(8)} | {('220 V', i): [18] for i in range(7)} | {('700 V', 0): [19], ('1000 V', 0): [19], ('1000 V', 3): [19], ('1000 V', 4): [19]}

# Wideband (pp.1-20 .. 1-22).  flatness: "% + uV" per band (11 bands, relative to 1 kHz, 1 yr); absolute: "90d 1yr 2yr", "% + uV", first five bands only
WB = {   # range -> (flatness list, absolute string, printed page)
    '2.2 mV': (['0.10+0', '0.05+0', '0.05+0', '0.05+0', '0.07+1', '0.07+1', '0.07+1', '0.17+1', '0.30+1', '0.70+2', '1.00+2'], '0.5+1.2 0.6+1.5 0.8+2', 20),
    '7 mV': (['0.10+0', '0.05+0', '0.05+0', '0.05+0', '0.07+1', '0.07+1', '0.07+1', '0.1+1', '0.17+1', '0.37+1', '0.5+1'], '0.4+5 0.5+7 0.7+8', 20),
    '22 mV': (['0.10', '0.05', '0.05', '0.05', '0.07', '0.07', '0.07', '0.1', '0.17', '0.37', '0.6'], '0.4+10 0.5+13 0.7+16', 20),
    '70 mV': (['0.10', '0.05', '0.05', '0.05', '0.05', '0.05', '0.05', '0.1', '0.15', '0.35', '0.6'], '0.4+20 0.5+30 0.6+40', 21),
    '220 mV': (['0.10', '0.04', '0.04', '0.04', '0.04', '0.05', '0.05', '0.1', '0.15', '0.35', '0.6'], '0.3+60 0.4+80 0.5+100', 21),
    '700 mV': (['0.10', '0.03', '0.03', '0.03', '0.03', '0.05', '0.05', '0.1', '0.15', '0.35', '0.6'], '0.3+200 0.4+300 0.5+400', 21),
    '2.2 V': (['0.10', '0.03', '0.03', '0.03', '0.03', '0.05', '0.05', '0.1', '0.15', '0.35', '0.6'], '0.3+300 0.35+400 0.4+500', 21),
    '7 V': (['0.10', '0.03', '0.03', '0.03', '0.03', '0.05', '0.05', '0.1', '0.15', '0.35', '0.6'], '0.3+500 0.35+800 0.4+1000', 22),
}

PERIOD = ['90 day', '1 yr', '2 yr']


# ---------------------------------------------------------------------------------------------------------- builders
def _terms(text, pct):
    """'1700+1.3' / '200' / '0.1+1.3' -> (relative term value, uV)"""
    a, _, b = text.partition('+')
    return float(a), (float(b) if b else 0.0)


def spec(period, text, pct=False, uv_only=False):
    """Parsed specification via specmanager.parse_spec (so rel/abs come out exactly as the other files)."""
    if uv_only:
        raw = f'[{period}] Accuracy: +/-({float(text) * 1e-6:.6g} V)'
    else:
        a, b = _terms(text, pct)
        body = f'{a:g} % I.V.' if pct else f'{a:g} ppm I.V.'
        if b:
            body += f' + {b * 1e-6:.6g} V'
        raw = f'[{period}] Accuracy: +/-({body})'
    s = sm.parse_spec(raw)
    assert 'error' not in s, raw
    s['unit'] = s['unit'] or 'V'
    return s


def prm(lo, hi, unit, text, notes=()):
    return dict(tag='', lo=lo, hi=hi, unit=unit, text=text, annot='', notes=list(notes))


def entry(fname, label, page, amp, freq, specs, notes=()):
    params = [prm(amp[0], amp[1], 'V', f'{amp[0]:g} V to {amp[1]:g} V', notes)]
    if freq:
        params.append(prm(freq[0], freq[1], 'Hz', f'{fmt_hz(freq[0])} to {fmt_hz(freq[1])}'))
    r = dict(label=label, page=page, params=params, specs=specs, raw_other=[])
    r.update(sm.analyse_range(fname, label, params))
    return r


def amp_band(name):
    i = [n for n, _ in RANGES].index(name)
    return (0.0 if i == 0 else RANGES[i - 1][1], TOP[name])


def build():
    functions, problems = [], []
    P = lambda n: n + PDF_OFFSET      # printed page 1-n -> PDF page

    # ---- absolute AC (three periods) and the transfer-mode rows
    fa = dict(name='Voltage, AC [Sinewave, Absolute]', direction='input', page=P(9), ranges=[])
    ft = dict(name='Voltage, AC [AC/DC Transfer Mode, Absolute]', direction='input', page=P(10), ranges=[])
    for name, rows in ABS_AC.items():
        for i, row in enumerate(rows):
            lo, hi = AC_BANDS[i]
            specs = [spec(p, t, False) for p, t in zip(PERIOD, row.split())]
            fa['ranges'].append(entry(fa['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(ABS_AC_PAGE[name]), amp_band(name), (lo, hi), specs, ABS_NOTES.get((name, i), [])))
        for i, ppm in enumerate(ABS_TRANSFER.get(name, [])):
            lo, hi = AC_BANDS[i]
            ft['ranges'].append(entry(ft['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(ABS_AC_PAGE[name]), amp_band(name), (lo, hi),
                                      [spec('2 yr', str(ppm))], [11] + ABS_NOTES.get((name, i), [])))
    functions += [fa, ft]

    # ---- relative AC
    fr = dict(name='Voltage, AC [Relative]', direction='input', page=P(12), ranges=[])
    frt = dict(name='Voltage, AC [AC/DC Transfer Mode, Relative]', direction='input', page=P(12), ranges=[])
    for name, rows in REL_AC.items():
        for i, row in enumerate(rows):
            lo, hi = AC_BANDS[i]
            specs = [spec(p, t, False) for p, t in zip(PERIOD, row.split())]
            fr['ranges'].append(entry(fr['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(REL_AC_PAGE[name]), amp_band(name), (lo, hi), specs, REL_NOTES.get((name, i), [])))
        for i, ppm in enumerate(REL_TRANSFER.get(name, [])):
            lo, hi = AC_BANDS[i]
            frt['ranges'].append(entry(frt['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(REL_AC_PAGE[name]), amp_band(name), (lo, hi),
                                       [spec('2 yr', str(ppm))], [11] + REL_NOTES.get((name, i), [])))
    functions += [fr, frt]

    # ---- non-sine (1 yr, % of reading + uV)
    fn = dict(name='Voltage, AC [Non-sine, Absolute]', direction='input', page=P(14), ranges=[])
    for name, rows in NONSINE.items():
        for i, t in enumerate(rows):
            lo, hi = NS_BANDS[i]
            notes = [8] + ([9] if name in ('2.2 V', '22 V') else [])
            fn['ranges'].append(entry(fn['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(14), amp_band(name), (lo, hi), [spec('1 yr', t, True)], notes))
    functions.append(fn)

    # ---- DC
    for title, table in (('Voltage, DC', ABS_DC), ('Voltage, DC [Relative]', REL_DC)):
        f = dict(name=title, direction='input', page=P(15), ranges=[])
        for name, row in table.items():
            lo, hi = (0.0, TOP[name]) if name == '220 mV' else amp_band(name)
            f['ranges'].append(entry(title, name, P(15), (lo, hi), None, [spec(p, t) for p, t in zip(PERIOD, row.split())], [10]))
        functions.append(f)

    # ---- 24 hour AC stability
    fs = dict(name='Voltage, AC [24 hr Stability, Slow Filter]', direction='input', page=P(16), ranges=[])
    for name, vals in STAB24.items():
        for i, v in enumerate(vals):
            lo, hi = AC_BANDS[i]
            uv_only = name in ('2.2 mV', '7 mV', '22 mV')
            s = spec('24 hr', str(v), uv_only=uv_only)
            fs['ranges'].append(entry(fs['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(STAB_PAGE[name]), amp_band(name), (lo, hi), [s], [17] + STAB_NOTES.get((name, i), [])))
    functions.append(fs)

    # ---- wideband absolute accuracy (first five bands) and flatness (eleven bands)
    fw = dict(name='Voltage, AC [Wideband, Absolute]', direction='input', page=P(20), ranges=[])
    ff = dict(name='Flatness [Wideband, Relative to 1 kHz]', direction='input', page=P(20), ranges=[])
    for name, (flat, absolute, pg) in WB.items():
        trip = absolute.split()
        for i in range(5):
            lo, hi = WB_BANDS[i]
            fw['ranges'].append(entry(fw['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(pg), amp_band(name), (lo, hi),
                                      [spec(p, t, True) for p, t in zip(PERIOD, trip)], [12, 14]))
        for i, t in enumerate(flat):
            lo, hi = WB_BANDS[i]
            notes = [12, 13] + ([15] if i == 10 else []) + ([16] if (i == 10 and name == '7 V') else [])
            ff['ranges'].append(entry(ff['name'], f'{name} @ {fmt_hz(lo)} to {fmt_hz(hi)}', P(pg), amp_band(name), (lo, hi), [spec('1 yr', t, True)], notes))
    functions += [fw, ff]

    # ---- 5790B/AF 50 MHz absolute (p.1-22)
    faf = dict(name='Voltage, AC [Wideband, 5790B/AF 50 MHz Absolute]', direction='input', page=P(22), ranges=[])
    r = entry(faf['name'], '223.61 mV +/-4 % @ 50 MHz', P(22), (0.21466, 0.23255), (50e6, 50e6), [spec('1 yr', '0.23', True)], [20])
    r['range_max'] = None
    faf['ranges'].append(r)
    functions.append(faf)

    data = dict(schema=1, standard=dict(
        manufacturer='Fluke', model='5790B', description='AC Measurement Standard (5790B, wideband options /3 /5 /AF)',
        confidence_text='99 % confidence level, k = 2.58, normally distributed (printed p.1-9; the 5790B/AF 50 MHz line is 95 %, k = 2)',
        confidence_pct=99.0, reference='Fluke 5790B Operators Manual, Chapter 1 Electrical Specifications, printed pp.1-9 to 1-22 (PDF pp.19-32); '
                                       '"page" fields in this file are PDF page numbers (printed page = PDF page - 10)',
        revision='5790B OM R0 ENG', author='built from the manual page images by specs/build_5790b_standard_from_manual.py', approved_by='', approve_date='',
        source_pdf='5790B Manual.pdf', sheet_generated='', built=datetime.now().isoformat(timespec='seconds')),
        notes={str(k): v for k, v in NOTES.items()}, functions=functions)

    # explicit problems (ambiguities the schema cannot hold or the manual leaves open)
    def w(where, what, level='warn'):
        problems.append(dict(level=level, where=where, what=what))
    w('standard', 'Direction is "input" (the 5790B measures). specmanager.StandardSpec.lookup() defaults to direction="output": pass direction="input" (or None) to find these rows.')
    w('standard', 'Coverage: 99 % (k = 2.58) per printed p.1-9; specmanager divisor() uses 2.576 for 99 %.')
    w('Voltage, AC [Sinewave, Absolute] 2.2 V - 1000 V', 'Printed as a bare number under "ppm of Reading + uV" (no uV term, pp.1-10, 1-11, 1-13); stored as ppm of reading with a 0 V fixed term.')
    w('Voltage, AC [Relative] 2.2 V - 1000 V', 'Same as above (p.1-13): bare ppm numbers stored with 0 V fixed term.')
    w('Voltage, DC / [Relative] 2.2 V - 1000 V', 'Same as above (p.1-15): bare ppm numbers stored with 0 V fixed term.')
    w('Voltage, AC [AC/DC Transfer Mode, ...]', 'Column header is "AC/DC Transfer Mode +/- ppm 2 Years"; the manual does not say ppm of reading or give a uV term. Stored as ppm of reading, 2 yr only, values printed against the first four frequency rows only (10 Hz - 50 kHz) (printed pp.1-10 to 1-13). Verify before use.')
    w('Voltage, AC [Non-sine, Absolute] 7 mV / 70 mV', 'Printed frequency labels are typos: 7 mV first row "10 kHz - 45 Hz", 70 mV second row "45 kHz - 1 kHz" (p.1-14). Read as 10 Hz - 45 Hz and 45 Hz - 1 kHz (same as every other range).')
    w('Voltage, AC [Non-sine, Absolute] 220 V - 1000 V', 'No non-sine specification is printed for 220 V, 700 V, 1000 V (p.1-14); the table ends at 70 V.')
    w('Voltage, AC [Non-sine, Absolute]', 'Only a 1 year column is printed (tcal +/-5 degC); percent of reading converted to a fraction (0.1 % = 1E-3).')
    w('Voltage, AC [Wideband, Absolute]', 'The absolute accuracy columns (90 d / 1 yr / 2 yr) are printed against the first five frequency rows only (10 Hz - 500 kHz); rows 500 kHz - 50 MHz carry flatness only (pp.1-20 to 1-22). Layout read from the image: if the cells were merged across more rows this is wrong. 0 degC to 50 degC.')
    w('Voltage, AC [Wideband, Absolute] / Flatness', 'The flatness column prints a uV term only for 2.2 mV and 7 mV ("+ 0", "+ 1", "+ 2"); 22 mV to 7 V print the percent alone. Stored as printed (bare = 0 V fixed term).')
    w('Flatness [Wideband, Relative to 1 kHz]', 'Specification is RELATIVE to 1 kHz, 1 year, +/-3 degC (p.1-22 footnote 2); a "flatness" limit is a difference between two readings, not an absolute accuracy. 2-year values (x 1.5) and flatness temperature coefficient (ppm/degC) are not stored.')
    w('Flatness [Wideband, Relative to 1 kHz] 30 MHz - 50 MHz', '5790B/5 and 5790B/AF only (footnote 5); 7 V range limited to 3.5 V amplitude there (footnote 6).')
    w('Voltage, AC [Wideband, 5790B/AF 50 MHz Absolute]', 'Single point 223.61 mV at 50 MHz, +/-4 % window 214.66 to 232.55 mV; 95 % confidence (k=2) unlike the 99 % of the rest of the file; 23 degC +/-3 degC; includes serialized cable.')
    w('Voltage, AC [24 hr Stability, Slow Filter]', 'Secondary specification (stability), stored with period "24 hr": peak-to-peak uV (fixed term) for 2.2 mV / 7 mV / 22 mV and ppm of reading for 70 mV and up (p.1-16 row separator). The manual says secondary specs are already included in the uncertainty specifications; do not add them to the accuracy again.')
    w('Voltage, AC [Sinewave, Absolute] 10 Hz - 20 Hz', 'Footnotes: 9.5 - 10 Hz is +/-(1000 ppm + 1.5 uV) on 70 mV - 700 mV and +/-1000 ppm on 2.2 V - 70 V; these are NOT separate rows (see notes 1, 2).')
    w('Voltage, AC / DC ranges', 'Value bands (amp_lo, amp_hi) are contiguous: each range runs from the previous range top to its own nominal top (first range from 0). The manual\'s autorange limits (p.1-9, e.g. 220 mV range 60 mV - 220 mV, 1000 V upper limit 1050 V) overlap and are not used for the bands. DC starts at the 220 mV range (no lower DC ranges are specified, p.1-15).')
    w('Voltage, AC [Sinewave, Absolute] 70 V / 220 V', 'Footnote [3] (p.1-11) is printed on the range label: inputs >100 kHz with V*Hz >2.2E7 are typical. Attached as note 3 to every frequency row of the range; only the stated condition is typical. Likewise 1000 V 20 kHz - 100 kHz (note 5, >750 V) and 700 V / 1000 V 10 Hz - 20 Hz (note 4).')
    w('standard', 'NOT LOADED (no schema field): temperature coefficients and input resistance (pp.1-16 to 1-18), flatness temperature coefficient (pp.1-20 to 1-22), resolution tables (pp.1-9, 1-20 to 1-22), frequency measurement accuracy "100 ppm + 10 digits (10 Hz - 120 Hz), 100 ppm + 2 digits above 120 Hz" (p.1-19: needs the garbled frequency resolution table), A40/A40A shunt AUX input (p.1-20 header), reading rate / settling.')
    problems.extend(sm.validate_data(data))
    data['problems'] = problems
    return data


def main():
    data = build()
    out = HERE / 'standards' / 'fluke_5790b_standard.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    n = sum(len(f['ranges']) for f in data['functions'])
    print(f"{len(data['functions'])} functions, {n} rows, {len(data['problems'])} problems -> {out}")


if __name__ == '__main__':
    main()
