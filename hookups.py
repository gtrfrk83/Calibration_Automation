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
}
RED_JACK = {'VOHM': 'vohm', 'UAMP': 'ma', 'AMP10': 'a10'}

# which (meter, group) pairs have a diagram
AVAILABLE = {
    'mm325': ('VOHM', 'UAMP', 'AMP10'),
    'fluke110': ('VOHM', 'UAMP', 'AMP10', 'TEMP', 'VOLTALERT'),
    'fluke87v': ('VOHM', 'UAMP', 'AMP10', 'TEMP'),
}

# extra text for particular meters
EXTRA = {
    ('mm325', 'VOHM'): dict(caution='This section applies up to 540 V DC and 540 V AC. Keep clear of the plugs and calibrator terminals whenever the output is on.',
                           detail='Use CAT III 600 V leads with the shields fitted (manual p. 7).'),
    ('mm325', 'UAMP'): dict(caution='Never apply more than 200 mA to the VΩ µA mA jack (200 mA fuse, manual p. 11).'),
    ('mm325', 'AMP10'): dict(caution='Never apply more than 10 A. Above 6 A the meter allows 30 s of measurement, then 10 min of rest (manual p. 9).'),
    ('fluke87v', 'UAMP'): dict(caution='The mA µA input is fused: do not exceed the range of the point being tested.'),
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
