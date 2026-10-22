"""Command registry of the DMM drivers (scpi_dmm: Fluke 8846A / Agilent 34401A, keysight_truevolt, keysight_dacq) on the simulated bench."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
from drivers import Agilent34401A, Fluke8846A, Keysight34470A, Keysight34970A, Keysight34972A  # noqa: E402
from drivers.keysight_dacq import KeysightDacq  # noqa: E402
from drivers.keysight_truevolt import KeysightTruevolt  # noqa: E402
from drivers.scpi_dmm import ScpiDmm  # noqa: E402
from drivers.simulated import make_dacq_bench, make_dmm_bench  # noqa: E402
from drivers.transport import CommandLog  # noqa: E402

PASSWORD = 'S3cretPw'


def texts(inst, d='>>'):
    return [t for _ts, _i, direction, t in inst.log.entries if direction == d]


def opened(cls, model, factory=make_dmm_bench, **kw):
    inst = cls(factory(model)[2], CommandLog(), label=model)
    inst.open(verify_model=False)
    del inst.log.entries[:]
    return inst


def wire_tap(inst):
    sent = []
    orig_w, orig_q = inst.t.write, inst.t.query
    inst.t.write = lambda text: (sent.append(text), orig_w(text))[1]
    inst.t.query = lambda text: (sent.append(text), orig_q(text))[1]
    return sent


def counts(cls):
    reg = cmdreg.merge_commands(cls)
    return dict(total=len(reg), normal=sum(c.risk == 'normal' for c in reg.values()), output=sum(c.risk == 'output' for c in reg.values()),
                locked=sum(c.risk == 'locked' for c in reg.values()), verified=sum(c.verified for c in reg.values()),
                unverified=sum(not c.verified for c in reg.values()))


class NoOverride(unittest.TestCase):
    def test_wire_and_log_are_the_old_text(self):
        d = opened(Keysight34470A, '34470A')
        d.configure_point(dict(kind='DCV', range=10, plc=10))
        d.configure_point(dict(kind='ACV', range=1, filter_hz=20))
        d.configure_point(dict(kind='FREQ', range=1))
        self.assertEqual(texts(d), ['CONF:VOLT:DC 10', 'VOLT:DC:NPLC 10', 'CONF:VOLT:AC 1', 'VOLT:AC:BAND 20', 'CONF:FREQ DEF,MIN',
                                    'FREQ:RANG:LOW 3', 'FREQ:APER 1', 'FREQ:VOLT:RANG 1'])
        self.assertEqual(d.command_overrides_active(), [])
        self.assertFalse(any('OVERRIDE' in t for _a, _b, _c, t in d.log.entries))

    def test_dacq_channel_commands(self):
        d = opened(Keysight34970A, '34970A', make_dacq_bench)
        d.configure_point(dict(kind='ACV', range=1, filter_hz=20), 210)
        d.configure_point(dict(kind='FREQ', range=1, nominal=1000.0), 210)
        self.assertEqual(texts(d), ['CONF:VOLT:AC 1,(@210)', 'VOLT:AC:BAND 20,(@210)', 'ROUT:SCAN (@210)', 'TRIG:SOUR IMM',
                                    'CONF:FREQ 1000,(@210)', 'FREQ:VOLT:RANG 1,(@210)', 'FREQ:APER 1,(@210)', 'ROUT:SCAN (@210)', 'TRIG:SOUR IMM'])
        d.module_type(2)
        self.assertEqual(texts(d)[-1], 'SYST:CTYP? 200')


class Override(unittest.TestCase):
    def check(self, inst, key, template, call, want_wire):
        sent = wire_tap(inst)
        self.assertEqual(inst.use_commands({key: template}, uids={key: 'ab12'}), [])
        call()
        self.assertEqual(sent, [want_wire])                                    # the wire never carries the marker
        self.assertEqual(texts(inst), [want_wire + '  [OVERRIDE ov-ab12]'])    # only the log does
        self.assertEqual(inst.command_overrides_active(), ['ov-ab12'])

    def test_scpi_dmm(self):
        d = opened(Fluke8846A, '8846A')
        self.check(d, 'conf.dcv', 'CONF:VOLT:DC {range:.3f}', lambda: d.configure('DCV', 10), 'CONF:VOLT:DC 10.000')
        d = opened(Fluke8846A, '8846A')
        d.use_commands({'conf.acv': 'CONF:VOLT:AC {range:.2f}'}, uids={'conf.acv': 'u'})
        d.configure('ACV', 1)
        d.configure('DCV', 1)                                                  # a different key: unchanged
        self.assertEqual(texts(d), ['CONF:VOLT:AC 1.00  [OVERRIDE ov-u]', 'CONF:VOLT:DC 1'])

    def test_34401a_filter(self):
        d = opened(Agilent34401A, '34401A')
        self.check(d, 'det.band.slow', 'DET:BAND 20', d.set_ac_filter_slow, 'DET:BAND 20')

    def test_truevolt(self):
        d = opened(Keysight34470A, '34470A')
        self.check(d, 'nplc.dcv', 'VOLT:DC:NPLC {nplc:.1f}', lambda: d.set_nplc('DCV', 100), 'VOLT:DC:NPLC 100.0')
        d = opened(Keysight34470A, '34470A')
        d.use_commands({'band.acv': 'VOLT:AC:BAND {hz:.1f}'}, uids={'band.acv': 'k'})
        d.set_ac_filter('ACV', 20)
        d.set_ac_filter('ACI', 20)                                             # ACI is its own key
        self.assertEqual(texts(d), ['VOLT:AC:BAND 20.0  [OVERRIDE ov-k]', 'CURR:AC:BAND 20'])

    def test_dacq(self):
        d = opened(Keysight34970A, '34970A', make_dacq_bench)
        sent = wire_tap(d)
        d.use_commands({'nplc.dcv': 'VOLT:DC:NPLC {plc:.1f},{ch}'}, uids={'nplc.dcv': 'z'})
        d.configure_point(dict(kind='DCV', range=10, plc=1), 210)
        self.assertEqual(sent[:2], ['CONF:VOLT:DC 10,(@210)', 'VOLT:DC:NPLC 1.0,(@210)'])
        self.assertEqual(texts(d)[:2], ['CONF:VOLT:DC 10,(@210)', 'VOLT:DC:NPLC 1.0,(@210)  [OVERRIDE ov-z]'])
        self.assertFalse(any('OVERRIDE' in t for t in sent))


class Locked(unittest.TestCase):
    def test_locked_keys_refuse_overrides(self):
        cases = [(Fluke8846A, {'cal.unlock': 'CAL:SEC:STAT OFF,{password}', 'cal.lock': 'CAL:SEC:STAT ON,{password}',
                               'cal.sec.query': 'CAL:SEC:STAT?', 'cal.val': 'CAL:VAL {mode},{value}', 'cal.on.query': 'CAL? ON',
                               'cal.rec': 'CAL:REC'}),
                 (Keysight34470A, {'status.clear': '*CLS', 'err.query': 'SYST:ERR?'}),
                 (Keysight34970A, {'status.clear': '*CLS', 'err.query': 'SYST:ERR?'}),
                 (Keysight34972A, {'status.clear': '*CLS', 'err.query': 'SYST:ERR?'})]
        for cls, bad in cases:
            inst = cls(make_dmm_bench('8846A')[2], CommandLog())
            rej = inst.use_commands(bad)
            self.assertEqual({k for k, _u, _p in rej}, set(bad), cls.__name__)
            self.assertEqual(inst.command_overrides_active(), [])
            self.assertTrue(all(cmdreg.merge_commands(cls)[k].risk == 'locked' for k in bad))

    def test_every_cal_key_is_locked_and_never_editable(self):
        rows = {r['key']: r for r in Fluke8846A(make_dmm_bench('8846A')[2], CommandLog()).describe_commands()}
        cal = [r for k, r in rows.items() if k.startswith('cal.')]
        self.assertEqual(len(cal), 6)
        for r in cal:
            self.assertEqual((r['risk'], r['editable'], r['overridable']), ('locked', False, False), r['key'])
            self.assertTrue(r['ref'])
        self.assertFalse(any(r['editable'] for k, r in rows.items() if k.startswith('cal.')))
        self.assertTrue(rows['conf.dcv']['editable'])

    def test_only_the_8846a_has_cal_commands(self):
        for cls in (ScpiDmm, Agilent34401A, KeysightTruevolt, Keysight34470A, KeysightDacq):
            self.assertFalse([k for k in cmdreg.merge_commands(cls) if k.startswith('cal.')], cls.__name__)

    def test_secret_placeholder_is_declared(self):
        cmd = cmdreg.merge_commands(Fluke8846A)['cal.unlock']
        self.assertTrue(cmd.secret)
        self.assertEqual(cmd.placeholders['password'].type, 'secret')
        self.assertTrue(cmdreg.merge_commands(Fluke8846A)['cal.lock'].secret)
        self.assertFalse(any(c.secret for k, c in cmdreg.merge_commands(Fluke8846A).items() if not k.startswith('cal.')))


class Passwords(unittest.TestCase):
    def test_password_on_the_wire_but_never_in_the_log_or_registry(self):
        d = Fluke8846A(make_dmm_bench('8846A')[2], CommandLog(), label='8846A')
        d.connect_for_adjustment()
        sent = wire_tap(d)
        d.unlock_calibration(PASSWORD)
        d.adjust_step('DCV', 10)
        d.lock_calibration(PASSWORD)
        self.assertIn('CAL:SEC:STAT OFF,' + PASSWORD, sent)
        self.assertIn('CAL:SEC:STAT ON,' + PASSWORD, sent)
        self.assertIn('CAL:VAL DCV,10', sent)
        log = '\n'.join(d.log.lines())
        self.assertNotIn(PASSWORD, log)
        self.assertIn('CAL:SEC:STAT OFF,********', texts(d))
        self.assertIn('CAL:SEC:STAT ON,********', texts(d))
        self.assertNotIn(PASSWORD, repr(d.describe_commands()))

    def test_password_not_in_log_when_overrides_are_rejected(self):
        d = Fluke8846A(make_dmm_bench('8846A')[2], CommandLog(), label='8846A')
        d.open(verify_model=False)
        d.use_commands({'cal.unlock': 'CAL:SEC:STAT OFF,' + PASSWORD})
        d.unlock_calibration(PASSWORD)
        self.assertNotIn(PASSWORD, '\n'.join(d.log.lines()))
        self.assertEqual(d.command_overrides_active(), [])


class Describe(unittest.TestCase):
    def test_registries_are_sane(self):
        for cls in (ScpiDmm, Fluke8846A, Agilent34401A, KeysightTruevolt, Keysight34470A, KeysightDacq, Keysight34970A, Keysight34972A):
            reg = cmdreg.merge_commands(cls)
            self.assertEqual(cmdreg.lint_registry(reg), [], cls.__name__)
            self.assertEqual(cmdreg.validate_bundle({}, reg), [], cls.__name__)

    def test_describe_lists_the_registry(self):
        for cls, model, factory in ((Fluke8846A, '8846A', make_dmm_bench), (Agilent34401A, '34401A', make_dmm_bench),
                                    (Keysight34470A, '34470A', make_dmm_bench), (Keysight34970A, '34970A', make_dacq_bench)):
            inst = cls(factory(model)[2], CommandLog())
            rows = inst.describe_commands()
            reg = cmdreg.merge_commands(cls)
            self.assertEqual([r['key'] for r in rows], list(reg), cls.__name__)
            for r in rows:
                self.assertEqual(r['verified'], reg[r['key']].verified)
                self.assertEqual(r['editable'], reg[r['key']].risk == 'normal' and not reg[r['key']].secret)
                self.assertTrue(r['name'])

    def test_unverified_flags(self):
        dacq = cmdreg.merge_commands(Keysight34970A)
        for key in ('freq.aper', 'band.acv', 'band.aci', 'rout.scan', 'read'):
            self.assertFalse(dacq[key].verified, key)
        for key in ('conf.dcv', 'nplc.dcv', 'sys.rem', 'module.type'):
            self.assertTrue(dacq[key].verified, key)
        self.assertEqual(cmdreg.merge_commands(Keysight34972A).keys(), dacq.keys())
        tv = cmdreg.merge_commands(Keysight34470A)
        self.assertTrue(tv['freq.aper'].verified)                               # the Truevolt manual states the 1 s aperture
        self.assertFalse(tv['conf.cap'].verified)
        self.assertFalse(any(c.verified for k, c in cmdreg.merge_commands(Fluke8846A).items() if k.startswith('cal.')))

    def test_counts(self):
        self.assertEqual(counts(ScpiDmm), dict(total=15, normal=11, output=0, locked=4, verified=9, unverified=6))   # Stage 7: +status.clear, err.query, reset, opc.query
        self.assertEqual(counts(Fluke8846A), dict(total=21, normal=11, output=0, locked=10, verified=9, unverified=12))
        self.assertEqual(counts(Agilent34401A), dict(total=16, normal=12, output=0, locked=4, verified=10, unverified=6))
        self.assertEqual(counts(Keysight34470A), dict(total=26, normal=22, output=0, locked=4, verified=22, unverified=4))
        self.assertEqual(counts(Keysight34970A), dict(total=25, normal=21, output=0, locked=4, verified=18, unverified=7))
        self.assertEqual(counts(Keysight34972A), counts(Keysight34970A))


if __name__ == '__main__':
    unittest.main()
