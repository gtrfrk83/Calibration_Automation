"""A SYNTHETIC Cal Processor .MDD for the tests (the real Fluke 87V file was not available; its quirks are unverified).
Follows what mdd_importer_v49.parse_mdd reads: marker lines '</Name>' / '<Name/>', tab-delimited, a names row, a types row, data rows."""
from pathlib import Path

HEADER_COLS = ['App_Name', 'Manufacturer', 'Model', 'Description', 'Procedure_Name', 'CalInterval', 'App_Version']
TP_COLS = ['TP_ID', 'IsHeaderRow', 'DS_PageNo', 'Text_Function', 'Text_Nominal', 'Text_Tolerance', 'Text_SpecStatement', 'Tol_Low', 'Tol_High',
           'Text_AsFound', 'Text_AsLeft', 'Text_OutOfTol']
# (function, nominal, tolerance, spec, low, high)
ROWS = [
    ('DC Volts', '100.0 mV', '[0.05% + 1] mV', '0.05 % + 1', '99.00', '101.00'),                  # 1  tolerance unit mV? (printed V: see test) -> uses tolerance unit
    ('DC Volts', '1.000 V', '[0.05% + 1] V', '', '0.9990', '1.0010'),                         # 2
    ('DC Volts', '10.00 V', '[0.05% + 1] V', '', '9.990', '10.010'),                          # 3
    ('AC Volts', '1.000 V~@ 60 Hz', '[0.5% + 2] V', '', '0.990', '1.010'),                    # 4 (cell uses ~ as line separator: 'nominal~condition')
    ('AC Volts', '1.000 V~@ 1 kHz', '[0.5% + 2] V', '', '0.990', '1.010'),                    # 5
    ('Volts', '5.000 V', '[0.1% + 1] V', '', '4.990', '5.010'),                               # 6 neither AC nor DC named -> guessed DC
    ('Resistance', '1.000 kOhm', '[0.2% + 2] kOhm', '', '0.997', '1.003'),                    # 7
    ('Resistance', '100.0 Ohm', '[0.2% + 2] Ohm', '', '99.7', '100.3'),                       # 8
    ('Capacitance', '0.21 to 31 nF', 'Pass/Fail', '', '', ''),                                # 9 numeric range as nominal
    ('Capacitance', 'Open', 'Pass/Fail', '', '', ''),                                         # 10 functional check
    ('Frequency', '1.000 kHz~@ 600 mV', '[0.1% + 1] kHz', '', '0.999', '1.001'),             # 11 level as amplitude
    ('Temperature', '212.0 degF', '[1] degF', '', '211.0', '213.0'),                          # 12
    ('Duty Cycle', '50.0 %', '[0.2] %', '', '49.8', '50.2'),                                  # 13
    ('Conductance', '10.00 nS', '[1] nS', '', '9.00', '11.00'),                               # 14
    ('DC Volts', '1.000 V', '[x] furlong', '', '0.99', '1.01'),                               # 15 unit unknown -> NOT converted
    ('DC Volts', '2.000 V', '[x] V', '', '2.01', '1.99'),                                     # 16 inverted limits -> NOT converted
    ('DC Volts', '3.000 V', '[x] V', '', 'abc', '3.01'),                                      # 17 limits not numbers -> NOT converted
]
DANGEROUS = 'Commands'


def mdd_text(rows=None, with_readings=False, header_extra=None, make='Fluke', model='87V', interval='365 Days'):
    rows = ROWS if rows is None else rows
    h = ['Cal Processor', make, model, 'Multimeter, Digital - Handheld', 'SYNTH-87V', interval, '4.9']
    lines = ['</Data Sheet Header>', '\t'.join(HEADER_COLS), '\t'.join(['text'] * len(HEADER_COLS)), '\t'.join(h), '<Data Sheet Header/>']
    lines += ['</Test Points>', '\t'.join(TP_COLS), '\t'.join(['text'] * len(TP_COLS))]
    lines.append('\t'.join(['0', '1', '1', 'Header row', '', '', '', '', '', '', '', '']))
    for i, (fn, nom, tol, spec, lo, hi) in enumerate(rows, 1):
        af = '1.0001' if with_readings else ''
        lines.append('\t'.join([str(100 + i), '0', '1', fn, nom, tol, spec, lo, hi, af, '', '']))
    lines.append('<Test Points/>')
    # a section the importer must never run: commands / scripts
    lines += ['</Commands>', 'Name\tScript', 'text\ttext', 'boom\timport os; os.system("touch /tmp/mdd_executed_marker")', '<Commands/>']
    return '\r\n'.join(lines) + '\r\n'


def write_mdd(path, **kw):
    path = Path(path)
    path.write_bytes(mdd_text(**kw).encode('cp1252'))
    return path
