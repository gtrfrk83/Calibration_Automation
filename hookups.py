"""Cable-change prompts for the handheld-meter procedures: connection text and hook-up diagram for each
calibrator (Fluke 5560A or Fluke 5522A) and each meter family.

    import hookups
    plan = hookups.plan('mm325', hookups.calibrator_key('Fluke 5560A  (automatic output)'), 'UAMP', manual=False)
    ui.confirm_steps(root, 'Change the cables', plan['title'], plan['steps'], caution=plan['caution'], image=plan['image'])

The diagrams in diagrams/ are drawn by specs/build_hookups.py from the tables below, so the text and the pictures cannot disagree.
The connections differ between the two calibrators:

    function                     Fluke 5560A                          Fluke 5522A
    volts, ohms (2-wire), C      OUTPUT V/OHM HI / LO                 NORMAL HI / LO
    current up to 2.2 A          VI AUX (HI)  +  OUTPUT LO            AUX HI  +  AUX LO
    high current (10 A)          30A  +  OUTPUT LO                    20 A  +  AUX LO
    thermocouple                 TC                                   TC

5560A terminals light up green for voltage and blue for current. The 5560A layout is drawn from a photograph of the front panel;
the 5522A is a labelled schematic (see the README).
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
DIAGRAMS = HERE / 'diagrams'

CAL_LABEL = {'5560A': 'Fluke 5560A', '5522A': 'Fluke 5522A'}
GROUP_TITLE = {'VOHM': 'voltage, resistance and capacitance', 'UAMP': 'µA / mA current', 'AMP10': '10 A current',
               'TEMP': 'temperature (thermocouple)', 'VOLTALERT': 'VoltAlert'}

# calibrator terminals: (HI terminal, LO terminal, colour the 5560A lights it)
CAL_TERMS = {
    '5560A': {'VOHM': ('OUTPUT V/Ω HI', 'OUTPUT V/Ω LO', 'green'),
              'UAMP': ('VI AUX', 'OUTPUT V/Ω LO', 'blue'),
              'AMP10': ('30A', 'OUTPUT V/Ω LO', 'blue'),
              'VOLTALERT': ('OUTPUT V/Ω HI', 'OUTPUT V/Ω LO', 'green'),
              'TEMP': ('TC +', 'TC −', 'green')},
    '5522A': {'VOHM': ('NORMAL HI', 'NORMAL LO', None),
              'UAMP': ('AUX HI', 'AUX LO', None),
              'AMP10': ('20 A', 'AUX LO', None),
              'VOLTALERT': ('NORMAL HI', 'NORMAL LO', None),
              'TEMP': ('TC +', 'TC −', None)},
}

# meter families: the jack the RED lead uses for each connection ('vohm', 'ma', 'a10'); the BLACK lead is always COM
METERS = {
    'mm325': dict(name='Klein Tools MM325', jacks={'vohm': 'VΩ', 'ma': 'VΩ µA mA', 'a10': '10A', 'com': 'COM'}),
    'fluke110': dict(name='Fluke 110 series', jacks={'vohm': 'VΩ', 'ma': 'VΩ', 'a10': 'A', 'com': 'COM'}),
    'fluke87v': dict(name='Fluke 87V', jacks={'vohm': 'VΩ', 'ma': 'mA µA', 'a10': '10A', 'com': 'COM'}),
    # Fluke 77 Series IV: jacks named as printed on the case (photo of the real terminals): 2 x 2 block, top-left '400 mA', bottom-left '10A'
    # (the two fused inputs), top-right 'V Ω' (red), bottom-right 'COM' (black)
    'fluke77': dict(name='Fluke 77 Series IV', jacks={'vohm': 'V Ω', 'ma': '400 mA', 'a10': '10A', 'com': 'COM'}),
    # Fluke 175 / 177 / 179: the Calibration Information (pp. 2, 3, 9) names the jacks VΩ, 400 mA, 10 A and COM; their ORDER on the case is not shown in it (Figure 1 p. 3 draws
    # only the VΩ jack and one current jack): UNVERIFIED, confirm on the real meter
    'fluke170': dict(name='Fluke 175 / 177 / 179', jacks={'vohm': 'VΩ', 'ma': '400 mA', 'a10': '10A', 'com': 'COM'}),
    # Fluke 365 clamp meter: the Calibration Manual's Figure 1 (p. 5) labels two jacks 'VΩ' and 'COM'; the current points use the detachable jaw on a 20-turn coil
    # (no test leads in the jacks), so only the voltage / ohms hook-up is described here and the coil hook-ups are the spec's own groups (specs/fluke_365_pv.json)
    # Fluke 287 / 289: jacks as printed on the case (supplied photo): A, mA uA, COM, V Ohm
    'fluke28x': dict(name='Fluke 287 / 289', jacks={'vohm': 'VΩ', 'ma': 'mA µA', 'a10': 'A', 'com': 'COM'}),
    'fluke365': dict(name='Fluke 365', jacks={'vohm': 'VΩ', 'com': 'COM'}),
    # Fluke 374 / 375 / 376 / 376-II clamp meters: the Calibration Manual's Figure 1 (p. 2) labels two jacks 'VΩ' and 'COM' (the iFlex 2 mm jack is named 'far left' on p. 3);
    # the current points use the detachable jaw or the iFlex loop on a 50-turn coil, and the iFlex simulation uses the iFlex jack, so only the voltage / mV / ohms / capacitance
    # hook-up is described here and the other hook-ups are the spec's own groups (specs/fluke_376_pv.json)
    'fluke376': dict(name='Fluke 374 / 375 / 376 / 376-II', jacks={'vohm': 'VΩ', 'com': 'COM'}),
    # Fluke 323 / 324 / 325 clamp meters: Figure 4 (printed p. 11) labels two jacks 'VΩ' and 'COM'; the current and frequency points use the jaw on a 50-turn coil and the temperature
    # points their own group, so only the voltage / ohms / capacitance hook-up is described here and the other hook-ups are the spec's own groups (specs/fluke_323_pv.json)
    'fluke323': dict(name='Fluke 323 / 324 / 325', jacks={'vohm': 'VΩ', 'com': 'COM'}),
    # Fluke 381 clamp meter: Figure 1 (printed p. 5) shows a small far-left jack (the iFlex 2 mm input of the iFlex paragraph, printed p. 13), COM and VΩ; the current points use the jaw or the iFlex loop on a
    # 50-turn coil (or a single wire for 0 A dc), so only the voltage / ohms hook-up is described here and the other hook-ups are the spec's own groups (specs/fluke_381_pv.json)
    'fluke381': dict(name='Fluke 381', jacks={'vohm': 'VΩ', 'com': 'COM'}),
    # Fluke 333 / 334 / 335 / 336 / 337 clamp meters: the Calibration Information (printed p. 7, step 1) names the input jacks 'VΩ' and 'COM'; the current, inrush and frequency points use the jaw on a
    # 50-turn coil (no test leads in the jacks), so only the voltage / ohms / continuity hook-up is described here and the other hook-ups are the spec's own groups (specs/fluke_33x_pv.json)
    'fluke33x': dict(name='Fluke 333 / 334 / 335 / 336 / 337', jacks={'vohm': 'VΩ', 'com': 'COM'}),
    # Fluke 753 / 754 Documenting Process Calibrator: a 2 x 3 block of jacks (owner's photo, diagrams/fluke_753_754_terminals.png; Calibration Manual Figures 1-13, 15): top row 'VΩ RTD' (SOURCE side),
    # 'mA / mA Ω RTD', 'V' (MEASURE side); bottom row the three commons; TC mini-jack lower left.  The hook-ups are the spec's own groups (specs/fluke_753_754_pv.json, drawn by specs/build_hookups_753.py),
    # so there is no AVAILABLE entry; 'panels' are the owner's instrument reference pictures (front view, terminal close-up) the engine (fluke_753_754.py) shows when a group has no drawn picture
    'fluke753': dict(name='Fluke 753 / 754', jacks={'vohm': 'VΩ RTD', 'ma': 'mA Ω RTD', 'v': 'V', 'com': 'COM'}, panels=('fluke_753_754_terminals.png', 'fluke_753_754_front.png')),
}
RED_JACK = {'VOHM': 'vohm', 'UAMP': 'ma', 'AMP10': 'a10'}

# which (meter, group) pairs have a diagram
AVAILABLE = {
    'mm325': ('VOHM', 'UAMP', 'AMP10'),
    'fluke110': ('VOHM', 'UAMP', 'AMP10', 'TEMP', 'VOLTALERT'),
    'fluke87v': ('VOHM', 'UAMP', 'AMP10', 'TEMP'),
    'fluke77': ('VOHM', 'UAMP', 'AMP10'),
    'fluke170': ('VOHM', 'UAMP', 'AMP10', 'TEMP'),
    'fluke28x': ('VOHM', 'UAMP', 'AMP10', 'TEMP'),
    'fluke365': ('VOHM',),
    'fluke376': ('VOHM',),
    'fluke323': ('VOHM',),
    'fluke381': ('VOHM',),
    'fluke33x': ('VOHM',),
}

# extra text for particular meters
EXTRA = {
    ('mm325', 'VOHM'): dict(caution='This section applies up to 540 V DC and 540 V AC. Keep clear of the plugs and calibrator terminals whenever the output is on.',
                           detail='Use CAT III 600 V leads with the shields fitted (manual p. 7).'),
    ('mm325', 'UAMP'): dict(caution='Never apply more than 200 mA to the VΩ µA mA jack (200 mA fuse, manual p. 11).'),
    ('mm325', 'AMP10'): dict(caution='Never apply more than 10 A. Above 6 A the meter allows 30 s of measurement, then 10 min of rest (manual p. 9).'),
    ('fluke87v', 'UAMP'): dict(caution='The mA µA input is fused: do not exceed the range of the point being tested.'),
    ('fluke77', 'UAMP'): dict(caution='The 400 mA input is fused at 440 mA: never apply more than the point being tested (manual p. 4). '
                                      'The meter shows LEAd when the rotary switch moves to or from the mA position: check the leads are in the right jacks (p. 3).'),
    ('fluke77', 'AMP10'): dict(caution='The 10A input is fused at 11 A: never apply more than 10 A (20 A for 30 s at most, then 10 minutes rest; manual pp. 4, 6). '
                                       'Use leads rated for 10 A. The meter shows LEAd when the rotary switch moves to or from the A position (p. 3).'),
    ('fluke170', 'UAMP'): dict(caution='The 400 mA input is fused at 440 mA: never apply more than the point being tested (manual pp. 2, 3, 18). '
                                       'The meter shows LEAd when the rotary switch moves to or from the mA position: check the leads are in the right jacks (p. 2). '
                                       'For AC current, short the VΩ input to COM or leave it unconnected (p. 9).'),
    ('fluke170', 'AMP10'): dict(caution='The 10A input is fused at 11 A: never apply more than the point being tested (manual pp. 2, 3, 18). Use leads rated for 10 A. '
                                        'The meter shows LEAd when the rotary switch moves to or from the A position (p. 2). For AC current, short the VΩ input to COM or leave it unconnected (p. 9).'),
    ('fluke365', 'VOHM'): dict(caution='Up to 570 V ac or dc is applied to the VΩ and COM jacks (600 V CAT III meter). Use CAT III 600 V leads with the finger guards, connect COM before the live lead '
                                       'and remove the live lead first, and keep clear of the plugs and terminals whenever the output is on (Safety Information, pp. 2-3). '
                                       'Do not touch more than 30 V ac rms, 42 V ac peak or 60 V dc.'),
    ('fluke376', 'VOHM'): dict(caution='Up to 900 V ac or dc is applied to the VΩ and COM jacks (the jaw is marked CAT III 1000 V, CAT IV 600 V, Figure 1). Use CAT III 1000 V leads with the finger guards, connect COM before the live '
                                       'lead and remove the live lead first, and keep clear of the plugs and terminals whenever the output is on. The Calibration Manual gives no further safety information '
                                       '(it refers to the Users Manual).'),
    ('fluke323', 'VOHM'): dict(caution='Up to 600 V ac or dc is applied to the VΩ and COM jacks (the meter is marked CAT 600 V and CAT 300 V, Figure 4; the category numerals are not legible in the manual). Use leads rated for the category and 600 V with the finger guards, connect COM before the live '
                                       'lead and remove the live lead first, and keep clear of the plugs and terminals whenever the output is on. The Calibration Manual gives no further safety information.'),
    ('fluke381', 'VOHM'): dict(caution='Up to 1000 V ac or dc is applied to the VΩ and COM jacks (the jack panel is marked CAT III 1000 V, CAT IV 600 V, Figure 1). Use CAT III 1000 V leads with the finger guards, connect COM before the live '
                                       'lead and remove the live lead first, and keep clear of the plugs and terminals whenever the output is on. Do not touch more than 30 V ac rms, 42 V ac peak or 60 V dc (Safety Information, printed p. 2).'),
    ('fluke33x', 'VOHM'): dict(caution='Up to 600 V ac or dc is applied to the VΩ and COM jacks (CAT III 600 V, Pollution Degree II, Specifications printed p. 3; never use the meter above 600 V or 400 Hz, Safety Information printed p. 2). '
                                       'Use CAT III 600 V leads with the finger guards, connect COM before the live lead and remove the live lead first, and keep clear of the plugs and terminals whenever the output is on. '
                                       'Use caution above 60 V dc or 30 V ac.'),
    ('fluke170', 'TEMP'): dict(caution='Use the correct cable (Table 3 note 3). The meter and the thermocouple adapter must be at the same temperature: allow 20 minutes before the temperature points (Table 3 note 4).'),
}
GENERIC_CAUTION = {
    'AMP10': 'Leads, plugs and terminals carry high current: use leads rated for 10 A or more, check the meter fuse, and make sure every connection is tight.',
    'VOLTALERT': 'Mains-level voltage is present at the plug. Keep your hands clear while the output is on.',
}


def calibrator_key(text: str) -> str:
    """'5560A' or '5522A' from the calibrator selector text (the 5560A when it cannot be told)."""
    t = (text or '').upper()
    return '5522A' if ('5522' in t or '5520' in t) else '5560A'


def image_path(meter: str, cal: str, group: str):
    path = DIAGRAMS / f'hook_{meter}_{cal}_{group}.png'
    return path if path.is_file() else None


PANEL_PICTURES = {'34401A': 'keysight34401a_panel.png', '34460A': 'keysight34460a_panel.png', '34461A': 'keysight34461a_34465a_panel.png',
                  '34465A': 'keysight34461a_34465a_panel.png', '8846A': 'fluke8846a_panel.png', 'MDO4000C': 'tektronix_mdo4000_panel.png',
                  '287': 'fluke28x_panel.png', '289': 'fluke28x_panel.png'}


def panel_image(model):
    """The front-panel picture the owner supplied for an instrument (diagrams/, see README_panels.txt), or None when there is none for that model
    (the 34470A has none yet) or the file is missing.  Shown beside the connection steps; it never changes a step."""
    name = PANEL_PICTURES.get(str(model or '').upper().replace('-', ''))
    path = DIAGRAMS / name if name else None
    return path if path is not None and path.is_file() else None


BENCH_CURRENT_JACK = {'34401A': 'I', '34460A': '3A', '34461A': '3A', '34465A': '3A'}


def bench_image(model, wiring, terminal=None, nominal=None, rng=None, open_input=False):
    """Drawn hook-up picture (Fluke 5560A to the meter's front jacks) for a bench DMM, or the supplied front-panel photo when there is none
    (rear terminals, capacitance, other models).  wiring: 'VOLT' | 'RES2' | 'RES4' | 'CURRENT' | 'ZERO'.  Shown beside the connection steps; it never changes a step.
    Jack choice for current (34461A / 34465A: 10 A for terminal FRONT_10A else 3 A; 8846A: 400 mA jack up to the 400 mA range, else 10 A) is from the panel photos: UNVERIFIED."""
    m = str(model or '').upper().replace('-', '')
    if str(terminal or '').upper() == 'REAR':
        return panel_image(model)
    if wiring == 'ZERO':
        key = 'OPEN' if open_input else 'SHORT'
    elif wiring == 'CURRENT':
        if m == '8846A':
            size = abs(float(rng if rng is not None else (nominal or 0)))
            key = 'I_400MA' if size <= 0.4 else 'I_10A'
        elif str(terminal or '').upper() == 'FRONT_10A' and m in ('34461A', '34465A'):
            key = 'I_10A'
        else:
            key = 'I_' + BENCH_CURRENT_JACK.get(m, '3A')
    elif wiring in ('VOLT', 'RES2', 'RES4'):
        key = wiring
    else:
        return panel_image(model)
    path = DIAGRAMS / f'hook_{m}_5560A_{key}.png'
    return path if path.is_file() else panel_image(model)


def has(meter, group) -> bool:
    return group in AVAILABLE.get(meter, ())


def lit_note(cal, color):
    if cal == '5560A' and color:
        return f' The terminals light up {color} on the 5560A: check that these are the lit ones.'
    return ' Match the terminal labels on the front panel.'


def summary(meter, cal, group) -> str:
    """One line for the point-detail panel."""
    hi, lo, _ = CAL_TERMS[cal][group]
    m = METERS[meter]
    if group in ('TEMP',):
        return f'{CAL_LABEL[cal]} TC connector -> thermocouple cable -> 80AK adapter in the meter {m["jacks"]["vohm"]} and COM jacks.'
    if group == 'VOLTALERT':
        return f'Double-banana plug on {CAL_LABEL[cal]} {hi} / {lo}; hold the meter VoltAlert tip against the plug.'
    return f'{CAL_LABEL[cal]} {hi} -> meter {m["jacks"][RED_JACK[group]]} jack (red); {lo} -> COM jack (black).'


def plan(meter: str, cal: str, group: str, manual: bool = False):
    """dict(title, steps, caution, image) for a cable change, or None when this meter/group has no hook-up."""
    if not has(meter, group):
        return None
    hi, lo, color = CAL_TERMS[cal][group]
    m = METERS[meter]
    extra = EXTRA.get((meter, group), {})
    steps = [('Meter dial', 'Turn the meter dial to OFF before you move any lead.'),
             ('Standby', 'Put the calibrator in STANDBY before you rewire.' if manual else 'The calibrator is put in STANDBY before you rewire.')]
    if group == 'TEMP':
        steps += [('Calibrator', f'K-type thermocouple cable (mini-plug on both ends) into the {CAL_LABEL[cal]} TC connector, observing polarity.'),
                  ('Meter', f'Other end into the Fluke 80AK adapter, and the adapter into the meter {m["jacks"]["vohm"]} (+) and COM (−) jacks.'),
                  ('Settle', 'Allow the junctions to stabilise before reading.')]
    elif group == 'VOLTALERT':
        steps += [('Calibrator', f'Double-banana plug into the {CAL_LABEL[cal]} {hi} and {lo} terminals.'),
                  ('Meter', 'No meter leads: hold the meter VoltAlert tip against the plug when the point asks for it.')]
    else:
        red = m['jacks'][RED_JACK[group]]
        steps += [('Calibrator', f'RED lead to {hi}, BLACK lead to {lo}.' + lit_note(cal, color)),
                  ('Meter', f'RED lead in the {red} jack, BLACK lead in the COM jack. Push both plugs in fully.')]
        if group == 'UAMP' and meter == 'mm325':
            steps[-1] = ('Meter', 'The meter end can stay as it is: RED in the VΩ µA mA jack, BLACK in COM. Only the calibrator end moves.')
        if extra.get('detail'):
            steps.append(('Leads', extra['detail']))
    steps.append(('Check', 'Compare your connections with the diagram, then continue.'))
    return dict(title=f'Change the cables: {GROUP_TITLE[group]}  -  {CAL_LABEL[cal]} to {m["name"]}', steps=steps,
                caution=extra.get('caution') or GENERIC_CAUTION.get(group), image=image_path(meter, cal, group))
