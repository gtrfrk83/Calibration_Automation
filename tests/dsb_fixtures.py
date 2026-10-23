"""Sample datasheets for the Datasheet Builder tests.  The accuracy numbers are ILLUSTRATIVE (shaped like real 6.5-digit DMM / generator / scope
specifications) - they are test data, not any manufacturer's published limits."""
import datasheet_builder as db

PERIODS = [('90d', '90 days'), ('1y', '1 year')]


def waive_unimplemented(ds):
    """Rule 5: the suite has no uncertainty calculation for frequency, period, scope or generator rows yet, so a sheet that has them publishes only with a recorded waiver
    for each of those points.  The fixtures carry that waiver (the author's explicit choice, in the sheet) so they save as 'ready' like before."""
    import datasheet_builder_rules as rules
    ids = [p.id for fn, p in ds.all_points() if fn.kind in rules.SHOULD_HAVE_KINDS and fn.kind not in rules.RESOLVABLE_KINDS]
    if ids:
        rules.set_waiver(ds, ids, 'not_implemented', '', who='fixture')
    return ds



def dmm_34461a_like():
    """DC volts, AC volts (frequency bands), 2-wire ohms, DC current, capacitance, frequency: a 34461A-like sheet, periods 90d / 1y."""
    ds = db.Datasheet('Keysight', '34461A', '34461A example datasheet', revision='example')
    ds.set_periods(PERIODS, '1y')
    # DC volts
    f = ds.add_function('DCV')
    for fs, res in (('0.1', '1e-7'), ('1', '1e-6'), ('10', '1e-5'), ('100', '1e-4'), ('1000', '1e-3')):
        f.add_range(fs, res)
    ds.set_spec(f, {'90d': '0.0030 % of reading + 0.0030 % of range', '1y': '0.0040 % of reading + 0.0035 % of range'})
    f.add_rule(db.PointRule('pct', 'percent_of_range', {'percents': ['10', '50', '100'], 'bipolar': True, 'zero': True}))
    # AC volts with frequency bands
    a = ds.add_function('ACV')
    for fs, res in (('0.1', '1e-7'), ('1', '1e-6'), ('10', '1e-5'), ('100', '1e-4'), ('750', '1e-3')):
        a.add_range(fs, res)
    for lo, hi, p90, p1y in (('3', '5', '0.50 % of reading + 0.02 % of range', '0.50 % of reading + 0.03 % of range'),
                              ('5', '10', '0.10 % of reading + 0.02 % of range', '0.10 % of reading + 0.03 % of range'),
                              ('10', '20000', '0.02 % of reading + 0.02 % of range', '0.03 % of reading + 0.03 % of range'),
                              ('20000', '50000', '0.05 % of reading + 0.04 % of range', '0.06 % of reading + 0.05 % of range'),
                              ('50000', '100000', '0.20 % of reading + 0.08 % of range', '0.25 % of reading + 0.10 % of range'),
                              ('100000', '300000', '1.0 % of reading + 0.5 % of range', '1.2 % of reading + 0.5 % of range')):
        ds.set_spec(a, {'90d': p90, '1y': p1y}, f_lo=lo, f_hi=hi)
    a.add_rule(db.PointRule('ac', 'percent_of_range', {'percents': ['10', '100']}, frequencies={'mode': 'list', 'values': ['1 kHz', '50 kHz']}))
    # 2-wire ohms
    o = ds.add_function('OHM2')
    for fs, res in (('100', '1e-4'), ('1000', '1e-3'), ('10000', '1e-2'), ('100000', '0.1'), ('1000000', '1')):
        o.add_range(fs, res)
    ds.set_spec(o, {'90d': '0.010 % of reading + 0.004 % of range', '1y': '0.012 % of reading + 0.004 % of range'})
    o.add_rule(db.PointRule('r', 'percent_of_range', {'percents': ['100']}))
    # DC current
    i = ds.add_function('DCI')
    for fs, res in (('0.0001', '1e-10'), ('0.001', '1e-9'), ('0.01', '1e-8'), ('0.1', '1e-7'), ('1', '1e-6'), ('3', '1e-5')):
        i.add_range(fs, res)
    ds.set_spec(i, {'90d': '0.05 % of reading + 0.02 % of range', '1y': '0.05 % of reading + 0.025 % of range'})
    i.add_rule(db.PointRule('i', 'percent_of_range', {'percents': ['100']}))
    # capacitance, frequency
    c = ds.add_function('CAP')
    c.add_range('0.000000001', '1e-12')
    c.add_range('0.000001', '1e-9')
    ds.set_spec(c, '1 % of reading + 0.5 % of range')
    c.add_rule(db.PointRule('c', 'percent_of_range', {'percents': ['100']}))
    q = ds.add_function('FREQ')
    q.add_range('300000', '1e-3')
    ds.set_spec(q, '0.01 % of reading + 3 counts')
    q.add_rule(db.PointRule('f', 'fixed', {'values': ['10 Hz', '1 kHz', '100 kHz']}, amplitude='1 V'))
    db.regenerate(f), db.regenerate(a), db.regenerate(o), db.regenerate(i), db.regenerate(c), db.regenerate(q)
    # 750 V at 50 kHz is beyond every calibrator's table: the Sheet check (rule 5) wants its missing uncertainty waived, in writing, before the sheet publishes
    import datasheet_builder_rules as rules
    rules.set_waiver(ds, ['acv.r750.+750@50000'], 'no_source', '', who='fixture')
    return waive_unimplemented(ds)


def acv_bands_sheet():
    """A one-function AC volts sheet with a per-range x per-frequency-band table and band-edge points."""
    ds = db.Datasheet('Acme', 'ACV-1', 'ACV band example')
    ds.set_periods([('1y', '1 year')], '1y')
    a = ds.add_function('ACV')
    a.add_range('1', '1e-5')
    a.add_range('10', '1e-4')
    for rid in ('r1', 'r10'):
        ds.set_spec(a, '0.1 % of reading + 0.05 % of range', range_id=rid, f_lo='10', f_hi='1000')
        ds.set_spec(a, '0.3 % of reading + 0.1 % of range', range_id=rid, f_lo='1000', f_hi='20000')
    a.add_rule(db.PointRule('edges', 'percent_of_range', {'percents': ['50']}, frequencies={'mode': 'bands', 'at': 'edges'}))
    db.regenerate(a)
    return ds


def generator_33220a_like():
    ds = db.Datasheet('Agilent', '33220A', '33220A example generator sheet')
    ds.set_periods(PERIODS, '1y')
    amp = ds.add_function('GEN_AMPL', settings={'waveform': 'SIN', 'load': 'INF', 'amp_unit': 'Vrms'})
    amp.add_range('10', '1e-4')
    ds.set_spec(amp, '1 % of reading + 1 mV')
    amp.add_rule(db.PointRule('a', 'fixed', {'values': ['0.02 V', '0.5 V', '2 V']}, frequencies={'mode': 'list', 'values': ['1 kHz']}))
    amp.add_rule(db.PointRule('a2', 'fixed', {'values': ['2 V']}, frequencies={'mode': 'list', 'values': ['100 kHz', '1 MHz']}))
    fq = ds.add_function('GEN_FREQ')
    fq.add_range('20000000', '1e-3')
    ds.set_spec(fq, {'90d': '1 ppm of reading', '1y': '2 ppm of reading'})
    fq.add_rule(db.PointRule('f', 'fixed', {'values': ['1 kHz', '1 MHz', '10 MHz']}, amplitude='1 V'))
    off = ds.add_function('GEN_OFFSET')
    off.add_range('5', '1e-4')
    ds.set_spec(off, '1 % of reading + 2 mV')
    off.add_rule(db.PointRule('o', 'fixed', {'values': ['-2 V', '2 V']}))
    fl = ds.add_function('GEN_FLAT')
    fl.add_range('7', '1e-3')
    ds.set_spec(fl, '0.1 dB')
    fl.add_rule(db.PointRule('fl', 'frequency_sweep', {'nominal': '0'}, frequencies={'mode': 'list', 'values': ['10 kHz', '100 kHz', '1 MHz', '10 MHz', '20 MHz']}, amplitude='1 V'))
    for fn in ds.functions:
        db.regenerate(fn)
    return waive_unimplemented(ds)


def scope_tds2000c_like():
    ds = db.Datasheet('Tektronix', 'TDS2024C', 'TDS2024C example scope sheet')
    ds.set_periods([('1y', '1 year')], '1y')
    g = ds.add_function('SCOPE_GAIN')
    for vdiv in ('0.005', '0.05', '0.5', '5'):
        g.add_range(str(db.D(vdiv) * 8), id='v' + vdiv.replace('.', 'p'))
    ds.set_spec(g, '3 % of reading')
    g.add_rule(db.PointRule('g', 'percent_of_range', {'percents': ['90'], 'bipolar': True}, settings={'coupling': 'DC'}))
    bw = ds.add_function('SCOPE_BW')
    bw.add_range('10')
    ds.set_spec(bw, '3 dB', mode='low_only', bound='3')
    bw.add_rule(db.PointRule('b', 'frequency_sweep', {'nominal': '0'}, frequencies={'mode': 'list', 'values': ['50 MHz', '100 MHz', '200 MHz']}, amplitude='3 V'))
    tb = ds.add_function('SCOPE_TIMEBASE')
    tb.add_range('10')
    ds.set_spec(tb, '50 ppm of reading')
    tb.add_rule(db.PointRule('t', 'fixed', {'values': ['1 ms', '10 ms']}))
    tr = ds.add_function('SCOPE_TRIGGER')
    tr.add_range('10')
    tr.add_rule(db.PointRule('tr', 'frequency_sweep', {'nominal': '1'}, frequencies={'mode': 'list', 'values': ['10 MHz', '100 MHz']}, amplitude='0.5 V'))
    for fn in ds.functions:
        db.regenerate(fn)
    return waive_unimplemented(ds)
