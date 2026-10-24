"""Command registry of the LeCroy WaveSurfer 4104HD, Tektronix MDO4000C and Fluke 287/289 drivers (no tkinter, no hardware):
an override changes the wire text and adds the OVERRIDE marker to the log only; LeCroy VBS overrides keep to the whitelisted form;
locked / output keys refuse overrides; describe_commands() lists the registry."""
import collections
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cmdreg  # noqa: E402
from drivers import Fluke28x, TektronixMDO4000C, WaveSurfer4104HD  # noqa: E402
from drivers.simulated import SimBench, make_bench  # noqa: E402
from drivers.simulated_28x import SimFluke28x  # noqa: E402
from drivers.simulated_mdo import make_mdo_bench  # noqa: E402
from drivers.transport import CommandLog  # noqa: E402


def texts(inst, d='>>'):
    return [t for _ts, _i, direction, t in inst.log.entries if direction == d]


def tap(inst):
    """Record what really reaches the transport (the log may carry the OVERRIDE marker, the wire must not)."""
    sent = []
    w = inst.t.write                      # the simulators answer a query through write(), so this sees queries too
    inst.t.write = lambda text: (sent.append(text), w(text))[1]
    return sent


def scope():
    _bench, _ft, st = make_bench()
    inst = WaveSurfer4104HD(st, CommandLog(), label='WS')
    inst.open()
    del inst.log.entries[:]
    return inst


def mdo():
    _bench, t = make_mdo_bench()
    inst = TektronixMDO4000C(t['scope'], CommandLog(), label='MDO')
    inst.connect()
    del inst.log.entries[:]
    return inst


def dmm28x():
    inst = Fluke28x(SimFluke28x(SimBench(), '289'), CommandLog(), label='289')
    inst.connect()
    del inst.log.entries[:]
    return inst


class LeCroyOverride(unittest.TestCase):
    def test_no_override_wire_and_log_are_the_old_text(self):
        w = scope()
        sent = tap(w)
        w.set_vertical_scale(2, 0.05, settle=0)
        self.assertEqual(sent, ["VBS 'app.Acquisition.C2.VerScale=0.05'", 'VBS? "return=app.Acquisition.C2.VerScale"'])
        self.assertEqual(texts(w), sent)
        self.assertEqual(w.command_overrides_active(), [])
        self.assertFalse(any('OVERRIDE' in t for _a, _b, _c, t in w.log.entries))

    def test_override_changes_wire_and_marks_only_the_log(self):
        w = scope()
        sent = tap(w)
        rej = w.use_commands({'vert.scale.set': "VBS 'app.Acquisition.C{ch}.VerScale={value:.3f}'"}, uids={'vert.scale.set': 'ab12'})
        self.assertEqual(rej, [])
        w.set_vertical_scale(1, 0.05, settle=0)
        self.assertEqual(sent[0], "VBS 'app.Acquisition.C1.VerScale=0.050'")                    # no marker on the wire
        self.assertEqual(texts(w)[0], "VBS 'app.Acquisition.C1.VerScale=0.050'  [OVERRIDE ov-ab12]")
        self.assertEqual(texts(w)[1], 'VBS? "return=app.Acquisition.C1.VerScale"')              # the read-back is not overridden: no marker
        self.assertEqual(w.command_overrides_active(), ['ov-ab12'])

    def test_property_path_can_be_edited_within_the_whitelist(self):
        w = scope()
        sent = tap(w)
        rej = w.use_commands({'hor.scale.set': "VBS 'app.Acquisition.Horizontal.HorScale2={seconds:.6g}'"}, uids={'hor.scale.set': 'p1'})
        self.assertEqual(rej, [])
        try:
            w.set_timebase(1e-3, settle=0)
        except Exception:
            pass                                    # the simulator does not know the edited path; only the wire matters here
        self.assertEqual(sent[0], "VBS 'app.Acquisition.Horizontal.HorScale2=0.001'")
        self.assertTrue(texts(w)[0].endswith('[OVERRIDE ov-p1]'))

    def test_vbs_override_outside_the_whitelisted_form_is_refused(self):
        w = scope()
        bad = {
            'vert.scale.set': "VBS 'app.Utility.Remote.Hack={value}'",                           # path not under Acquisition / Measure / Math
            'vert.offset.set': "VBS 'app.Acquisition.C{ch}.VerOffset={value}:app.Quit'",       # statement separator
            'coupling.set': "VBS 'app.Acquisition.C{ch}.Coupling=\"{coupling}\" ': CreateObject",
            'bandwidth.set': "VBS 'app.Acquisition.C{ch}.BandwidthLimit=\"{limit}\" ' WScript.Shell",
            'hor.scale.set': "WSCRIPT 'app.Acquisition.Horizontal.HorScale={seconds:.12g}'",      # verb changed
            'trig.type.edge': "VBS 'app.Acquisition.Calibrate=1'",                                # Calibrat is forbidden
            'trig.slope.set': "VBS 'app.SaveRecall.Setup.DoSaveSetup={slope}'",
            'vert.scale.get': 'VBS? "return=app.Os.Exec"',
        }
        rej = w.use_commands(bad)
        self.assertEqual({k for k, _u, _p in rej}, set(bad), rej)
        self.assertTrue(all(any(getattr(p, 'code', '') == 'vbs' or 'vbs' in str(p).lower() or 'placeholder' in getattr(p, 'code', '')
                                for p in probs) for _k, _u, probs in rej), rej)
        self.assertEqual(w.command_overrides_active(), [])
        self.assertTrue(len(texts(w, '!!')) >= len(bad))
        sent = tap(w)
        w.set_vertical_scale(1, 0.05, settle=0)
        self.assertEqual(sent[0], "VBS 'app.Acquisition.C1.VerScale=0.05'")                     # factory text, no marker
        self.assertFalse(any('OVERRIDE ov' in t and 'REJECTED' not in t for _a, _b, d, t in w.log.entries if d == '>>'))

    def test_validator_alone_refuses_non_vbs_edits_of_a_vbs_command(self):
        cmd = WaveSurfer4104HD.COMMANDS['vert.scale.set']
        self.assertEqual(cmd.lang, 'vbs')
        self.assertEqual(cmdreg.validate("VBS 'app.Measure.P1.X={value}'", cmd, 'WaveSurfer4104HD')[:1].__len__(), 1)   # ch is required
        self.assertTrue(cmdreg.validate('*RST', cmd, 'WaveSurfer4104HD'))
        self.assertEqual(cmdreg.validate("VBS 'app.Acquisition.C{ch}.VerScale={value:.3f}'", cmd, 'WaveSurfer4104HD'), [])

    def test_trailing_space_commands_are_registered_exactly_but_cannot_be_edited(self):
        w = scope()
        sent = tap(w)
        w.configure_p1(1, 'PkPk', show=True)
        self.assertIn("VBS 'app.Measure.P1.ParamEngine=\"PkPk\" ' ", sent)
        self.assertIn("VBS 'app.Measure.P1.View=True ' ", sent)
        rej = w.use_commands({'p1.view.on': "VBS 'app.Measure.P1.View=False ' ", 'p1.engine.set': "VBS 'app.Measure.P1.ParamEngine=\"{engine}\"'"})
        self.assertEqual({k for k, _u, _p in rej}, {'p1.view.on', 'p1.engine.set'})

    def test_locked_and_generic_keys_refuse_overrides(self):
        w = scope()
        keys = {'vbs.get': 'VBS? "return={path}"', 'vbs.set.number': "VBS '{path}={value}'", 'vbs.set.text': "VBS '{path}=\"{text}\" '"}
        rej = w.use_commands(keys)
        self.assertEqual({k for k, _u, _p in rej}, set(keys))                  # refused even with the factory text
        self.assertEqual(w.command_overrides_active(), [])

    def test_helpers_with_a_caller_supplied_path_still_work_and_log_the_same(self):
        w = scope()
        sent = tap(w)
        w.vbs_set_number('app.Acquisition.C1.VerScale', 0.5)
        w.vbs_set_text('app.Acquisition.C1.Coupling', 'DC1M')
        self.assertEqual(w.vbs_get('app.Acquisition.C1.Coupling'), 'DC1M')
        self.assertEqual(sent[:2], ["VBS 'app.Acquisition.C1.VerScale=0.5'", "VBS 'app.Acquisition.C1.Coupling=\"DC1M\" '"])

    def test_query_retry_takes_a_key_or_the_old_text(self):
        w = scope()
        self.assertEqual(w.query_retry('vert.scale.get', values={'ch': '1'}).split()[0], 'VBS')
        self.assertEqual(w.query_retry('VBS? "return=app.Acquisition.C1.VerScale"').split()[0], 'VBS')
        with self.assertRaises(Exception):
            w.query_retry('vert.scale.set', values={'ch': '1', 'value': 1.0})  # a set key is not a query

    def test_unverified_trigger_commands_are_flagged(self):
        reg = cmdreg.merge_commands(WaveSurfer4104HD)
        for key in ('trig.slope.set', 'trig.slope.get', 'trig.level.set', 'trig.level.get', 'trig.mode.set', 'trig.mode.get'):
            self.assertFalse(reg[key].verified, key)
        for key in ('vert.scale.set', 'coupling.set', 'hor.scale.set', 'p1.value.get', 'trig.source.set'):
            self.assertTrue(reg[key].verified, key)


class MdoOverride(unittest.TestCase):
    def test_no_override_wire_equals_log(self):
        m = mdo()
        sent = tap(m)
        m.trigger_edge('CH1', level=0.5, slope='FALL', mode='NORMal')
        self.assertEqual(sent, ['TRIGger:A:TYPe EDGe', 'TRIGger:A:EDGE:SOUrce CH1', 'TRIGger:A:EDGE:SLOpe FALL', 'TRIGger:A:MODe NORMal',
                                'TRIGger:A:LEVel 0.5'])
        self.assertEqual(texts(m), sent)
        self.assertEqual(m.command_overrides_active(), [])

    def test_override_changes_wire_and_marks_only_the_log(self):
        m = mdo()
        sent = tap(m)
        rej = m.use_commands({'trig.level': 'TRIGger:A:LEVel:VALue {level:.3f}'}, uids={'trig.level': 'cd34'})
        self.assertEqual(rej, [])
        m.trigger_edge('CH1', level=0.5)
        self.assertEqual(sent[-1], 'TRIGger:A:LEVel:VALue 0.500')
        self.assertEqual(texts(m)[-1], 'TRIGger:A:LEVel:VALue 0.500  [OVERRIDE ov-cd34]')
        self.assertEqual([t for t in texts(m) if 'OVERRIDE' in t].__len__(), 1)
        self.assertEqual(m.command_overrides_active(), ['ov-cd34'])

    def test_override_of_a_set_keeps_its_readback_pairing(self):
        m = mdo()
        sent = tap(m)
        m.use_commands({'ch.scale.set': 'CH{ch}:SCAle {value:.4f}'}, uids={'ch.scale.set': 'sc'})
        m.channel(1, vscale=0.5, position=None)
        self.assertEqual(texts(m)[:2], ['CH1:COUPling DC', 'CH1:SCAle 0.5000  [OVERRIDE ov-sc]'])
        self.assertEqual(sent[2], 'CH1:SCAle?')
        # an override that removes the query from the paired read-back is refused as a bundle
        m2 = mdo()
        rej = m2.use_commands({'ch.scale.get': 'CH{ch}:SCAle'})
        self.assertTrue(rej)

    def test_legacy_raw_text_set_verified_still_works(self):
        m = mdo()
        sent = tap(m)
        m.set_verified('CH1:SCAle', 'CH1:SCAle?', 0.2)
        self.assertEqual(sent, ['CH1:SCAle 0.2', 'CH1:SCAle?'])

    def test_locked_output_and_calibration_keys_refuse_overrides(self):
        m = mdo()
        bad = {'afg.on': 'AFG:OUTPut:STATe ON', 'afg.off': 'AFG:OUTPut:STATe OFF', 'default.factory': 'FACtory', 'status.clear': '*CLS',
               'diag.run': 'DIAg:STATE EXECute', 'spc.start': 'CALibrate:INTERNal:STARt', 'esr.query': '*ESR?', 'evmsg.query': 'EVMsg?',
               'opc.query': '*OPC?', 'data.encdg': 'DATa:ENCdg ASCIi', 'sys.header.off': 'HEADer OFF', 'generic.query': '{query}',
               'no.such.key': 'X'}
        rej = m.use_commands(bad)
        self.assertEqual({k for k, _u, _p in rej}, set(bad))
        self.assertEqual(m.command_overrides_active(), [])

    def test_dangerous_text_in_an_editable_key_is_refused(self):
        m = mdo()
        rej = m.use_commands({'acq.stop': '*RST', 'acq.run': 'ACQuire:STATE RUN;FACtory',
                              'meas.stat.off': 'CALibrate:INTERNal:STARt'})
        self.assertEqual({k for k, _u, _p in rej}, {'acq.stop', 'acq.run', 'meas.stat.off'})

    def test_output_commands_are_risk_output_and_rf_is_unverified(self):
        reg = cmdreg.merge_commands(TektronixMDO4000C)
        self.assertEqual({k for k, c in reg.items() if c.risk == 'output'}, {'afg.on', 'afg.off'})
        rf = [k for k in reg if k.startswith('rf.')]
        self.assertEqual(len(rf), 15)
        self.assertFalse(any(reg[k].verified for k in rf))
        self.assertEqual(TektronixMDO4000C.COMMANDS['rf.center'].template, 'RF:FREQuency {v:.9g}')

    def test_rf_cmd_sends_the_registry_key(self):
        m = mdo()
        m.use_commands({'rf.center': 'RF:FREQuency {v:.3e}'}, uids={'rf.center': 'rf'})
        m.rf_cmd('center', v=1e9)
        m.rf_cmd('avg_count', n=8)
        self.assertEqual(texts(m), ['RF:FREQuency 1.000e+09  [OVERRIDE ov-rf]', 'ACQuire:NUMAVg 8'])


class Fluke28xLocked(unittest.TestCase):
    def test_protocol_codes_are_registered_locked_and_never_overridden(self):
        d = dmm28x()
        reg = cmdreg.merge_commands(Fluke28x)
        self.assertEqual({k: (c.template, c.risk, c.kind) for k, c in reg.items()},
                         {'id': ('ID', 'locked', 'query'), 'qm': ('QM', 'locked', 'query'), 'qdda': ('QDDA', 'locked', 'query')})
        rej = d.use_commands({'id': 'DS', 'qm': 'RI', 'qdda': 'RMP'})
        self.assertEqual({k for k, _u, _p in rej}, {'id', 'qm', 'qdda'})
        self.assertEqual(d.command_overrides_active(), [])
        d.primary()
        d.display()
        self.assertEqual(texts(d), ['QM', 'QDDA'])
        self.assertFalse(any('OVERRIDE ov' in t and 'REJECTED' not in t for _a, _b, _c, t in d.log.entries))

    def test_no_reset_or_memory_commands_are_registered(self):
        banned = {'DS', 'RI', 'RMP'}
        self.assertFalse(banned & {c.template for c in cmdreg.merge_commands(Fluke28x).values()})


class Describe(unittest.TestCase):
    # (count, {risk: n}, {verified: n}) pinned so a new command has to be classified on purpose
    EXPECT = {
        'lecroy': (33, {'normal': 27, 'locked': 6, 'output': 0}, {True: 24, False: 9}),
        'mdo': (102, {'normal': 78, 'locked': 22, 'output': 2}, {True: 86, False: 16}),
        '28x': (3, {'normal': 0, 'locked': 3, 'output': 0}, {True: 3, False: 0}),
    }

    def rows(self):
        return {'lecroy': (WaveSurfer4104HD, scope()), 'mdo': (TektronixMDO4000C, mdo()), '28x': (Fluke28x, dmm28x())}

    def test_describe_lists_the_registry_and_counts(self):
        for name, (cls, inst) in self.rows().items():
            reg = cmdreg.merge_commands(cls)
            self.assertEqual(cmdreg.lint_registry(reg), [], name)
            self.assertEqual(cmdreg.validate_bundle({}, reg), [], name)
            rows = inst.describe_commands()
            self.assertEqual([r['key'] for r in rows], list(reg), name)
            n, risks, ver = self.EXPECT[name]
            self.assertEqual(len(rows), n, name)
            c_risk = collections.Counter(r['risk'] for r in rows)
            c_ver = collections.Counter(r['verified'] for r in rows)
            for k, v in risks.items():
                self.assertEqual(c_risk.get(k, 0), v, (name, k))
            for k, v in ver.items():
                self.assertEqual(c_ver.get(k, 0), v, (name, k))
            for r in rows:
                self.assertEqual(r['editable'], r['risk'] == 'normal', (name, r['key']))
                self.assertEqual(r['overridden'], False)

    def test_every_template_renders_with_its_sample_values(self):
        for cls in (WaveSurfer4104HD, TektronixMDO4000C, Fluke28x):
            for key, cmd in cmdreg.merge_commands(cls).items():
                vals = {n: cmdreg._default_sample(p) for n, p in cmd.placeholders.items()}
                text = cmdreg.render(cmd, vals)
                self.assertTrue(text, key)
                self.assertEqual(cmdreg.validate(cmd.template, cmd, cls.__name__), [], key)
                if cls is not Fluke28x and cmd.kind == 'query' and cmd.lang != 'vbs':
                    self.assertIn('?', text, key)
                if cmd.lang == 'vbs':
                    self.assertTrue(text.startswith(('VBS ', 'VBS? ')), key)

    def test_describe_follows_an_override(self):
        w = scope()
        w.use_commands({'vert.offset.set': "VBS 'app.Acquisition.C{ch}.VerOffset={value:.4f}'"}, uids={'vert.offset.set': 'zz'})
        row = {r['key']: r for r in w.describe_commands()}['vert.offset.set']
        self.assertEqual((row['overridden'], row['uid'], row['current']), (True, 'ov-zz', "VBS 'app.Acquisition.C{ch}.VerOffset={value:.4f}'"))
        self.assertEqual(row['factory'], "VBS 'app.Acquisition.C{ch}.VerOffset={value}'")
        self.assertEqual(row['readback'], 'vert.offset.get')


if __name__ == '__main__':
    unittest.main()
