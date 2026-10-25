"""Golden-transcript cases for the Tektronix TBS2000B driver (drivers/tektronix_tbs2000b.py) and engine (tbs2000b_verification.py).  Not a test module.

Kept out of tests/golden_capture.py / tests/golden_engines.py (they only register these two functions) so the TBS2000B work touches the shared harness by
a few additive lines.  `driver_cases(c)` is DRIVER_CASES['tektronix_tbs2000b'] (cases and resets), `engine_run()` is golden_engines.RUNS['tbs2000b'].
"""
from __future__ import annotations

from drivers.simulated_tbs2000b import make_tbs_bench
from drivers.tektronix_tbs2000b import TektronixTBS2000B
from drivers.transport import TransportError

COVERAGE = {
    'TektronixTBS2000B': dict(
        covered=['connect', 'cleanup', 'opc', 'check_errors', 'set_verified', 'set_enum_verified', 'default_setup', 'run_self_test', 'self_cal', 'select_only',
                 'channel', 'position', 'acquire_mode', 'run', 'num_acq', 'wait_acquisitions', 'timebase', 'record_length', 'delay', 'trigger_edge',
                 'trigger_mode', 'set_level_50', 'trigger_state', 'measure_setup', 'meas_value', 'measure', 'waveform', 'reset_to_defaults'],
        no_command=['model_from_idn']),                                     # static: parses the *IDN? text already read
}


def driver_cases(c):
    from tests.golden_capture import Scripted
    bench, t = make_tbs_bench('2204B')
    m = c.inst(TektronixTBS2000B, t['scope'], opened=False, label='TBS2000B')
    c.run('TektronixTBS2000B.connect', m.connect)
    c.run('TektronixTBS2000B.opc[no timeout]', m.opc)
    c.run('TektronixTBS2000B.opc[timeout]', m.opc, 60)
    c.run('TektronixTBS2000B.check_errors[ok]', m.check_errors, 'ctx')
    c.run('TektronixTBS2000B.default_setup', m.default_setup)
    c.run('TektronixTBS2000B.select_only', m.select_only, 2)
    c.run('TektronixTBS2000B.channel[all]', m.channel, 1, vscale=0.2, position=-5.0, probe=1, coupling='DC', bw_limit=True, offset=0.8)
    c.run('TektronixTBS2000B.channel[defaults]', m.channel, 3)
    c.run('TektronixTBS2000B.position', m.position, 1, 0.0)
    c.run('TektronixTBS2000B.set_verified', m.set_verified, 'ch.scale.set', 'ch.scale.get', 0.2, ch='1')
    c.run('TektronixTBS2000B.set_enum_verified', m.set_enum_verified, 'ch.coupling.set', 'ch.coupling.get', 'DC', ch='1')
    c.run('TektronixTBS2000B.acquire_mode[average]', m.acquire_mode, 'AVErage', 16)
    c.run('TektronixTBS2000B.acquire_mode[sample]', m.acquire_mode, 'SAMple')
    c.run('TektronixTBS2000B.run', m.run)
    c.run('TektronixTBS2000B.num_acq', m.num_acq)
    c.run('TektronixTBS2000B.wait_acquisitions', m.wait_acquisitions, 1, timeout=5.0, poll=0.0)
    c.run('TektronixTBS2000B.timebase', m.timebase, 1e-3)
    c.run('TektronixTBS2000B.record_length', m.record_length)
    c.run('TektronixTBS2000B.delay', m.delay, 1e-3)
    c.run('TektronixTBS2000B.trigger_edge[noise reject]', m.trigger_edge, 'CH1', slope='RISe', mode='AUTO', coupling='NOISErej')
    c.run('TektronixTBS2000B.trigger_edge[line]', m.trigger_edge, 'LINE', coupling=None)
    c.run('TektronixTBS2000B.trigger_mode', m.trigger_mode, 'NORMal')
    c.run('TektronixTBS2000B.set_level_50', m.set_level_50)
    c.run('TektronixTBS2000B.trigger_state', m.trigger_state)
    c.run('TektronixTBS2000B.measure_setup', m.measure_setup, 'PK2Pk', 1)
    c.run('TektronixTBS2000B.meas_value', m.meas_value)
    c.run('TektronixTBS2000B.measure', m.measure, 'MEAN', 1, count=2, timeout=5.0)
    c.run('TektronixTBS2000B.waveform', m.waveform, 2)                        # CH2 is the displayed channel (select_only above)
    c.run('TektronixTBS2000B.run_self_test', m.run_self_test)
    c.run('TektronixTBS2000B.self_cal', m.self_cal)
    c.run('TektronixTBS2000B.cleanup', m.cleanup)
    # branches the simulator cannot reach
    err = c.inst(TektronixTBS2000B, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='TBS2000B')
    c.run('TektronixTBS2000B.check_errors[command error]', err.check_errors, 'setup')
    flat = c.inst(TektronixTBS2000B, Scripted([(r'^CH1:SCAle\?', '0.9')]), label='TBS2000B')
    c.run('TektronixTBS2000B.set_verified[mismatch]', flat.set_verified, 'ch.scale.set', 'ch.scale.get', 0.2, ch='1')
    bwnum = c.inst(TektronixTBS2000B, Scripted([(r'^CH1:COUPling\?', 'DC'), (r'^CH1:BANdwidth\?', '2.0000E+08'), (r'^CH1:PRObe:GAIN\?', '1.0'),
                                                (r'^CH1:POSition\?', '0.0')]), label='TBS2000B')
    c.run('TektronixTBS2000B.channel[bandwidth answered as a frequency]', bwnum.channel, 1)
    flat2 = c.inst(TektronixTBS2000B, Scripted([(r'^CH1:COUPling\?', 'AC')]), label='TBS2000B')
    c.run('TektronixTBS2000B.set_enum_verified[mismatch]', flat2.set_enum_verified, 'ch.coupling.set', 'ch.coupling.get', 'DC', ch='1')
    bad = c.inst(TektronixTBS2000B, Scripted([(r'^MEASUrement:IMMed:VALue\?', '9.9000E+37')]), label='TBS2000B')
    c.run('TektronixTBS2000B.meas_value[invalid]', bad.meas_value)
    few = c.inst(TektronixTBS2000B, Scripted([(r'^ACQuire:NUMACq\?', '350')]), label='TBS2000B')
    c.run('TektronixTBS2000B.wait_acquisitions[too few]', few.wait_acquisitions, 5, timeout=0.0, poll=0.0)
    short = c.inst(TektronixTBS2000B, Scripted([(r'^WFMOutpre:NR_Pt\?', '3'), (r'^WFMOutpre:XINcr\?', '1E-9'), (r'^WFMOutpre:XZEro\?', '0'),
                                                (r'^WFMOutpre:YMUlt\?', '0.1'), (r'^WFMOutpre:YOFf\?', '0'), (r'^WFMOutpre:YZEro\?', '0'),
                                                (r'^CURVe\?', ':CURVE 1,2,3')]), label='TBS2000B')
    c.run('TektronixTBS2000B.waveform[record too short]', short.waveform, 1)
    failing = c.inst(TektronixTBS2000B, Scripted([(r'^DIAg:RESUlt:FLAg\?', 'FAIL'), (r'^DIAg:RESUlt:LOG\?', '"FAIL--ACQ"')]), label='TBS2000B')
    c.run('TektronixTBS2000B.run_self_test[fails]', failing.run_self_test)
    nolog = c.inst(TektronixTBS2000B, Scripted([(r'^DIAg:RESUlt:FLAg\?', 'PASS'), (r'^DIAg:RESUlt:LOG\?', TransportError('timeout'))]), label='TBS2000B')
    c.run('TektronixTBS2000B.run_self_test[log query fails]', nolog.run_self_test)
    badcal = c.inst(TektronixTBS2000B, Scripted([(r'^\*CAL\?', '1'), (r'^CALibrate:RESults:SPC\?', 'FAIL')]), label='TBS2000B')
    c.run('TektronixTBS2000B.self_cal[fails]', badcal.self_cal)
    wrong = c.inst(TektronixTBS2000B, Scripted([(r'\*IDN\?', 'TEKTRONIX,TDS 2024C,C012345,CF:91.1CT FV:v24.00')]), opened=False, label='TBS2000B')
    c.run('TektronixTBS2000B.connect[wrong model]', wrong.connect)
    # Stage 7 reset
    bench, t = make_tbs_bench('2204B')
    r = c.inst(TektronixTBS2000B, t['scope'], opened=False, label='TBS2000B')
    c.run('TektronixTBS2000B.connect[reset]', r.connect)
    c.run('TektronixTBS2000B.reset_to_defaults', r.reset_to_defaults)
    dirty = c.inst(TektronixTBS2000B, Scripted([(r'^\*ESR\?', '16'), (r'^EVMsg\?', '113,"Undefined header"')]), label='TBS2000B')
    c.run('TektronixTBS2000B.reset_to_defaults[event status not clean]', dirty.reset_to_defaults)


def engine_run():
    from tests import golden_capture as gc
    from tests.golden_engines import Runner as Build, pid, rec, sample
    import tbs2000b_verification as T
    c = gc.Case('engine_tbs2000b')
    bench, t = make_tbs_bench('2204B')
    wrapped = {k: rec(v) for k, v in t.items()}
    io = Build(c).build('tbs2000b_verification.IO.__init__', lambda: T.IO(dict(cal_baud=9600, cal_model='Fluke 5560A'), transports=wrapped))
    cfg = T.Config('2204B')

    class FakeApp:
        stop = False

        def __init__(self):
            self.io, self.cfg = io, cfg

        def request(self, kind, payload=None):
            return True

        def post(self, *a, **k):
            pass

        def cal_text(self):
            return 'Fluke 5560A'

    runner = T.Runner(FakeApp())
    c.run('tbs2000b_verification.IO.reset_at_start', io.reset_at_start, _log=io.log)       # Stage 7: first thing in every run
    pts = [p for p in T.POINTS if cfg.applies(p)]
    for p in sample(pts, lambda p: (p['kind'], p.get('vscale'), p.get('offset')), 12):
        c.run(f'tbs2000b_verification.Runner.run_point[{pid(p)}]', runner.run_point, p, _log=io.log)
    c.run('tbs2000b_verification.IO.close', io.close, _log=io.log)
    return c.entries
