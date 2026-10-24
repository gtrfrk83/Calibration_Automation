"""Prompt characterization of the WaveSurfer 4104HD engine (Procedures/WaveSurfer_WS4104HD.py).  Not a test module.  Registered in tests/ui_prompt_capture.SCENARIOS
as 'wavesurfer' (fixture tests/golden_ui/ui_prompts_wavesurfer.json); see that module for the canonical record and the two harnesses.

The WaveSurfer has no virtual-bench run (the simulated bench only does DC voltage), so the scenarios drive the REAL App on the stubbed Tk, method by method:
the technician's actions (Run Pending, Rerun Selected, Clear, the per-section start / next / retest buttons, the exports, closing the window) with the instrument
workers replaced by fakes that put the same events on `app.events` the real workers put (offset / bandwidth / impedance / time base / trigger / noise) and the
DC voltage point methods running on the simulated bench (drivers/simulated.make_bench) as in tests/golden_engines.py.  `threading.Thread` is a synchronous stand-in
inside the engine module and the Tk widgets that return values are mocks, so the order of the prompts is deterministic.  The report writers are fakes (no file is
written, no reportlab / openpyxl needed).  What is recorded is every prompt the engine shows, in order, with the answer it consumed (tests/ui_prompt_capture.py).
"""
from __future__ import annotations

import queue
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

from ui_port import Answers


class _SyncThread:
    """threading.Thread that runs its target at start() (the workers only put events on app.events; the prompts come from the pump)."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None, **_k):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return False


def _periodic(app):
    cls = type(app)
    return {cls.process_events, cls._unified_tick, cls.update_tab_titles}


def _widget_factory(**attrs):
    def make(*a, **k):
        m = mock.MagicMock()
        m.selection.return_value = ()
        m.get_children.return_value = ()
        for key, val in attrs.items():
            setattr(m, key, val)
        return m
    return make


def _run_wavesurfer(make_harness):
    import threading
    import tkinter.ttk
    import WaveSurfer_WS4104HD as W
    import datamode
    import procmods_engine
    from drivers.simulated import make_bench
    import drivers
    out = {}

    def prompts(hn):
        return hn.port.prompts if hasattr(hn, 'port') else hn.prompts

    def new(answers=None, sim_bench=False):
        hn = make_harness(answers)
        hn.start()
        thread_ns = types.SimpleNamespace(**{k: getattr(threading, k) for k in dir(threading) if not k.startswith('__')})
        thread_ns.Thread = _SyncThread
        for obj, name, val in ((tkinter.ttk, 'Treeview', _widget_factory()), (tkinter.ttk, 'Progressbar', _widget_factory()), (W, 'threading', thread_ns),
                               (sys.modules['time'], 'sleep', lambda s: None)):
            p = mock.patch.object(obj, name, val, create=True)
            p.start()
            hn.patches.append(p)
        hn.root.winfo_children = lambda: []
        a = W.RMSNoiseApp(hn.root)
        hn.app = a
        a.instrument_id.set('WS-1')
        a.serial.set('S-1')
        a.sync_asset()
        a.visa_address.set('sim')
        a.fluke_address.set('sim')
        a.utree = mock.MagicMock()
        a.utree.selection.return_value = ()
        if sim_bench:
            bench, ft, st = make_bench()
            transports = {'fluke': ft, 'scope': st}

            def open_bench(fluke_addr, baud, scope_addr, log, scope_timeout=10):
                fluke = drivers.Fluke5560A(transports['fluke'], log) if fluke_addr else None
                scope = drivers.WaveSurfer4104HD(transports['scope'], log) if scope_addr else None
                return fluke, scope
            a.open_bench = open_bench
            a._reset_notice = lambda text: True            # the unit-under-test notice (reset_startup.SessionNotice) is its own helper's business
        return hn, a

    def pump(hn, a, limit=4000):
        """Run what the Tk loop would: the event queue (process_events) and the one-shot after() calls, never the periodic tick."""
        skip = _periodic(a)
        for _ in range(limit):
            a.process_events()
            todo = [(fn, args) for fn, args in hn.root.q if getattr(fn, '__func__', None) not in skip]
            hn.root.q[:] = []
            if not todo and a.events.empty():
                return True
            for fn, args in todo:
                fn(*args)
        return False

    def done(name, hn):
        out[name] = list(prompts(hn))
        bypassed = hn.prompts if hasattr(hn, 'port') else []
        hn.stop()
        assert not bypassed, f'{name}: prompts bypassed the port: {bypassed[:2]}'

    def rule(hn, fn):
        hn.answers.rules.append(fn)

    def title_is(*titles, answer=False):
        return lambda r: answer if r.get('title') in titles else None

    # ---------------------------------------------------------------------------------------------------------------------------------
    # 1. the table buttons: Run Pending / Run Shown Section / Rerun Selected / Clear function, and the Instrument ID checks
    hn, a = new()
    a.show_function.set('All functions')
    a.run_section()                                                       # choose a function first -> info
    a.dc_running = True
    a.run_pending()                                                       # busy -> warning
    a.instrument_id.set('OTHER')
    a.sync_asset()                                                        # the ID cannot change while busy -> warning
    a.dc_running = False
    a.instrument_id.set('WS-1')
    a.instrument_id.set('')
    a.run_pending()                                                       # no Instrument ID -> info
    a.instrument_id.set('WS-1')
    a.sync_asset()
    a.rerun_selected()                                                    # nothing selected -> info
    a.utree.selection.return_value = ('r1',)
    a._entries_cache = {'r1': dict(kind='dcv', done=False, idx=0)}
    a.rerun_selected()                                                    # not measured yet -> info
    a._entries_cache = {'r1': dict(kind='dcv', done=True, idx=0)}
    a.dc_tree.get_children.return_value = ('i0',)
    a._mode_sets = {datamode.LEFT: dict({k: [] for k in W.RMSNoiseApp._SET_ATTRS}, dc_rows=[{}])}
    rule(hn, title_is('Replace the As Found reading?'))
    a.rerun_selected()                                                    # As Left exists: 'Replace the As Found reading?' -> No
    hn.answers.rules.clear()
    a.show_function.set('All functions')
    a.clear_function()                                                    # choose a function -> info
    a.show_function.set('DC voltage')
    rule(hn, title_is('Clear results'))
    a.clear_function()                                                    # 'Clear results?' -> No
    hn.answers.rules.clear()
    a.clear_function()                                                    # Yes, then 'Clear DCV results' -> Yes
    a.show_function.set('Offset (P1 mean)')
    a.clear_function()                                                    # the other functions clear without a second question
    a._mode_sets = {}
    done('table_buttons', hn)

    # 2. nothing pending: the demo data fills every function; an edit that cannot be applied; earlier results from an old version
    hn, a = new()
    a.load_demo_data()                                                    # 'Demo export ready'
    a.load_demo_data()                                                    # results exist -> 'Demo data' warning
    a.show_function.set('All functions')
    a.run_pending()                                                       # nothing pending -> info
    with mock.patch.object(a, 'pm_live_boundary', side_effect=procmods_engine.LiveApplyError('cannot apply')):
        a._pm_boundary('DC voltage')                                      # 'Edits not applied'
    tmp = Path(tempfile.mkdtemp())
    for base in W.RMSNoiseApp.CKPT_BASE.values():
        (tmp / f'{base}.json').write_text('{}', encoding='utf-8')

    class _Path(type(Path())):
        def with_name(self, name):
            return tmp / name
    with mock.patch.object(W, 'Path', _Path):
        a._ckpt_id = 'LEGACY-1'
        rule(hn, title_is('Earlier results found'))
        a._adopt_legacy_results('LEGACY-1')                               # 'Earlier results found' -> No
        hn.answers.rules.clear()
    done('demo_data_and_pm', hn)

    # 3. RMS noise: invalid settings, the new-test card, the channel cards, resume, retest, completion and errors
    hn, a = new()

    def fake_worker(address, channel, delay, samples, factor, limits, start_index=0, stop_index=None):
        a.events.put(('status', f'Connected: sim CH{channel}'))
        for idx in range(start_index, len(W.SCALES) if stop_index is None else stop_index):
            scale, limit = W.SCALES[idx], limits[idx]
            db = limit + 2.0
            a.events.put(('row', dict(timestamp='t', instrument='sim', channel=channel, scale_v_div=scale, rms_volts=1e-3, db=db, minimum_db=limit,
                                      margin_db=2.0, result='PASS', samples=samples, reference_factor_div=factor, note='')))
        a.events.put(('done', False))
    a.worker = fake_worker
    a.delay.set('0.0')
    a.start_test()                                                        # settle out of range -> 'Invalid configuration'
    a.delay.set('0.2')
    a.resume_test()                                                       # nothing saved -> returns silently
    rule(hn, title_is('New test'))
    a.start_test()                                                        # 'New test' -> Cancel
    hn.answers.rules.clear()
    a.channel.set('1')
    a.all_channels.set(False)
    a.start_test()                                                        # 'New test' -> OK, then 'Prepare channel' is asked by launch_remaining
    pump(hn, a)                                                           # the rows arrive, 'Test complete'
    a.retest_noise()                                                      # nothing selected -> info 'Select a result'
    a.tree.selection.return_value = ('i0',)
    a.tree.index.return_value = 0
    a.retest_noise()                                                      # 'Prepare channel' -> OK
    pump(hn, a)
    a.run_config = None
    a.retest_noise()                                                      # 'No saved run' -> info
    a.run_config = a.get_config()
    a.rows = a.rows[:1]
    a.limit_text.set('1,2,3')
    a.resume_test()                                                       # 'Invalid configuration'
    a.limit_text.set(','.join(map(str, W.LIMITS)))
    a.delay.set('0.3')
    a.resume_test()                                                       # 'Settings changed'
    a.delay.set('0.2')
    rule(hn, title_is('Prepare channel'))
    a.resume_test()                                                       # resume on the same channel: no card, the next range runs
    pump(hn, a)
    a.rows = []
    a.resume_test()                                                       # a channel change: 'Prepare channel' -> Cancel, Paused
    hn.answers.rules.clear()
    a.running = False
    a.events.queue.clear()
    a.events.put(('error', 'scope lost'))
    pump(hn, a)                                                           # 'Measurement error'
    a.noise_retest_index = 0
    a.events.put(('error', 'scope lost'))
    pump(hn, a)                                                           # retest failed -> 'Measurement error'
    a.events.put(('connection', True, 'LECROY,WS4104HD'))
    a.events.put(('fluke', True, '5560A'))
    a.events.put(('fluke', False, 'no reply'))
    pump(hn, a)                                                           # 'Fluke connection' info / error
    done('noise', hn)

    # 4. DC voltage on the simulated bench: Run automatically (the cable card per channel), retest, manual entry, the P1 question, errors
    hn, a = new(sim_bench=True)
    a.dc_settle.set('0.5')
    a.dc_auto_fluke.set(False)
    a.start_dcv_batch()                                                   # 'Automatic DCV' warning
    a.dc_auto_fluke.set(True)
    a.dc_p1_mode.set(False)
    a.start_dcv_batch()                                                   # same warning (P1 off)
    a.next_dcv()                                                          # 'Automatic mode' warning
    a.dc_p1_mode.set(True)
    a.dc_settle.set('99')
    a.next_dcv()                                                          # 'Settle time' error
    a.dc_settle.set('0.5')
    a.running = True
    a.next_dcv()                                                          # 'Busy'
    a.start_dcv_batch()                                                   # 'Busy'
    a.resume_dcv()                                                        # 'Busy'
    a.running = False
    rule(hn, title_is('Connect DCV cable — CH1'))
    a.start_dcv_batch()                                                   # the CH1 cable card -> Cancel: paused
    hn.answers.rules.clear()
    a.start_dcv_batch()                                                   # CH1 card -> OK; the first point runs on the simulated bench
    pump(hn, a, limit=6000)                                               # ... and the 80 points follow, one card per channel
    a.next_dcv()                                                          # all points done -> 'DCV complete'
    a.resume_dcv()                                                        # 'DCV complete'
    a.start_dcv_batch()                                                   # 'Complete'
    a.dc_tree.selection.return_value = ()
    a.retest_selected_dcv()                                               # 'Select a row'
    a.dc_tree.selection.return_value = ('i0', 'i1')
    a.retest_selected_dcv()                                               # 'Select a row'
    a.dc_tree.selection.return_value = ('i3',)
    a.dc_tree.index.return_value = 3
    a.dc_auto_fluke.set(False)
    a.retest_selected_dcv()                                               # 'Automatic retest' warning
    a.dc_auto_fluke.set(True)
    a.dc_settle.set('0')
    a.retest_selected_dcv()                                               # 'Settings' error
    a.dc_settle.set('0.5')
    rule(hn, title_is('Confirm DCV retest connection'))
    a.retest_selected_dcv()                                               # retest card -> Cancel
    hn.answers.rules.clear()
    a.retest_selected_dcv()                                               # retest card -> OK, the point runs again
    pump(hn, a)
    a.dc_running = True
    a.retest_selected_dcv()                                               # 'Busy'
    a.dc_running = False
    a.dc_tree.index.return_value = 200
    a.retest_selected_dcv()                                               # 'Not tested yet'
    a.dc_rows = a.dc_rows[:2]
    a.dc_tree.index.return_value = 5
    a.retest_selected_dcv()                                               # 'Not tested yet'
    # one point at a time: the manual card, the manual value, the P1 question, the invalid value, a read error and the safety message
    a.dc_batch = False
    a.dc_auto_fluke.set(False)
    a.dc_p1_mode.set(False)
    rule(hn, lambda r: 0.99 if r['kind'] == 'ask_number' and r['title'] == 'Measured DC voltage' else None)
    a.next_dcv()                                                          # 'Confirm DCV test setup' (manual output) -> OK, then 'Measured DC voltage'
    hn.answers.rules.clear()
    rule(hn, lambda r: float('nan') if r['kind'] == 'ask_number' else None)
    a.next_dcv()                                                          # NaN -> 'Invalid value'
    hn.answers.rules.clear()
    a.next_dcv()                                                          # 'Measured DC voltage' cancelled
    a.dc_p1_mode.set(True)
    a.next_dcv()                                                          # manual output, scope P1: card -> OK, read_dcv_scope (simulated bench)
    pump(hn, a)                                                           # 'Confirm P1 reading' -> Yes
    a.dc_auto_fluke.set(True)
    a.dc_batch = False
    a.next_dcv()                                                          # single automatic point: card, then 'Confirm automatic DCV reading'
    pump(hn, a)
    rule(hn, title_is('Confirm DCV test setup'))
    a.next_dcv()                                                          # setup card -> Cancel
    hn.answers.rules.clear()
    a.events.put(('dc_error', 'DCV communication failed'))
    a.events.put(('dc_safety', 'Fluke standby was NOT confirmed'))
    pump(hn, a)                                                           # 'DCV read error' / 'OUTPUT SAFETY WARNING'
    a.dc_rows = [dict(a.dcv_points()[0], measured_v=float('inf'))]
    a.record_dcv(a.dcv_points()[1], float('inf'), 'manual')              # 'Invalid value'
    rule(hn, title_is('Clear DCV results'))
    a.clear_dcv()                                                         # -> No
    hn.answers.rules.clear()
    done('dcv', hn)

    # 5. input impedance, offset, bandwidth, time base and trigger level: the cards, the busy / complete / settings messages, retests, errors
    hn, a = new()

    def put_idle(kind, *results):
        for r in results:
            a.events.put(r)
        a.events.put((f'{kind}_idle',))

    def imp_worker(point, settle, samples, scope_address, fluke_address, baud):
        put_idle('imp', ('imp_result', point, point['nominal_ohm'], [point['nominal_ohm']] * 3))

    def offset_worker(point, settle, fluke_addr, baud, scope_addr):
        put_idle('offset', ('offset_result', point, point['nominal_v'], point['nominal_v']))

    def bw_worker(point, settle, fluke_addr, baud, scope_addr):
        put_idle('bw', ('bw_result', point, point['amplitude_vpp'], point['amplitude_vpp'] * 0.9))

    def tb_worker(point, settle, samples, fluke_addr, baud, scope_addr):
        put_idle('tb', ('tb_result', point, [point['nominal_hz']] * 3, ()))

    def trig_worker(point, settle, fluke_addr, baud, scope_addr):
        reply = queue.Queue()
        a.events.put(('ask', 'Trigger before the level?', f'Did the scope trigger at {point["level_v"]}?', reply))
        put_idle('trig', ('trig_result', point, dict(triggered_short=False, triggered_past=True)))
    a.impedance_worker, a.offset_worker, a.bandwidth_worker, a.timebase_worker, a.trigger_worker = imp_worker, offset_worker, bw_worker, tb_worker, trig_worker

    # impedance: the connection card per input, the EXT impedance card, settings, busy, complete, retests
    a.running = True
    a.resume_impedance(); a.start_impedance_batch(); a.next_impedance()              # 'Busy' x3
    a.running = False
    a.imp_settle.set('99')
    a.next_impedance()                                                    # 'Settings'
    a.imp_settle.set('2.0')
    rule(hn, title_is('Confirm impedance connection'))
    a.next_impedance()                                                    # connection card -> Cancel
    hn.answers.rules.clear()
    a.start_impedance_batch()                                             # card -> OK; all 28 points follow (the EXT card inside)
    pump(hn, a, limit=6000)
    a.next_impedance()                                                    # 'Complete'
    a.start_impedance_batch()                                             # 'Complete'
    a.resume_impedance()                                                  # 'Complete'
    a.imp_tree.selection.return_value = ()
    a.retest_impedance()                                                  # 'Select a result'
    a.running = True
    a.retest_impedance()                                                  # 'Busy'
    a.running = False
    a.imp_tree.selection.return_value = ('i1',)
    a.imp_tree.index.return_value = 99
    a.retest_impedance()                                                  # 'Not tested yet'
    a.imp_tree.index.return_value = 2
    rule(hn, title_is('Confirm impedance retest'))
    a.retest_impedance()                                                  # retest card -> Cancel
    hn.answers.rules.clear()
    a.imp_samples.set('0')
    a.retest_impedance()                                                  # card -> OK, then 'Settings'
    a.imp_samples.set('3')
    a.retest_impedance()                                                  # card -> OK, the point runs again
    pump(hn, a)
    a.events.put(('imp_error', 'Fluke SCOPE MEASR failed'))
    a.events.put(('imp_safety', 'Fluke is not in SCOPE mode'))
    pump(hn, a)                                                           # 'Impedance measurement error' / 'FLUKE SCOPE MODE'
    a.clear_impedance()                                                   # -> Yes (below); the EXT card next
    a.imp_retest_index = None
    for pt in a.impedance_points()[:25]:
        a.record_impedance(pt, pt['nominal_ohm'], [pt['nominal_ohm']])
    a.imp_batch = False
    a.imp_connection_confirmed = True
    rule(hn, title_is('Confirm external trigger impedance'))
    a.next_impedance()                                                    # the EXT impedance card -> Cancel
    hn.answers.rules.clear()
    rule(hn, title_is('Clear impedance'))
    a.clear_impedance()                                                   # -> No
    hn.answers.rules.clear()
    a.clear_impedance()                                                   # -> Yes

    # offset
    a.running = True
    a.start_offset()                                                      # 'Busy'
    a.running = False
    a.offset_settle.set('99')
    a.start_offset()                                                      # 'Invalid setup'
    a.offset_settle.set('3.0')
    rule(hn, title_is('Confirm offset test method'))
    a.start_offset()                                                      # method card -> Cancel
    hn.answers.rules.clear()
    rule(hn, title_is('Offset cable connection'))
    a.start_offset()                                                      # method card -> OK; the cable card -> Cancel
    hn.answers.rules.clear()
    a.start_offset()                                                      # both cards OK; the 16 points follow
    pump(hn, a, limit=6000)
    a.start_offset()                                                      # 'Complete'
    a.offset_batch = True
    a.offset_running = False
    a.next_offset()                                                       # 'Complete'
    a.offset_tree.selection.return_value = ('i1',)
    a.offset_tree.index.return_value = 2
    rule(hn, title_is('Confirm offset retest'))
    a.retest_offset()                                                     # -> Cancel
    hn.answers.rules.clear()
    a.offset_settle.set('0')
    a.retest_offset()                                                     # card -> OK, then 'Settings'
    a.offset_settle.set('3.0')
    a.retest_offset()                                                     # card -> OK, runs
    pump(hn, a)
    a.events.put(('offset_error', 'scope P1 failed'))
    a.events.put(('offset_safety', 'Fluke standby not confirmed'))
    pump(hn, a)                                                           # 'Offset measurement error' / 'Fluke safety'

    # bandwidth
    a.offset_running = True
    a.start_bandwidth()                                                   # 'Busy'
    a.offset_running = False
    a.bw_settle.set('99')
    a.start_bandwidth()                                                   # 'Invalid settings'
    a.bw_settle.set('3.0')
    rule(hn, title_is('Confirm high-frequency test'))
    a.start_bandwidth()                                                   # -> Cancel
    hn.answers.rules.clear()
    rule(hn, title_is('Move 50 Ω signal cable'))
    a.start_bandwidth()                                                   # method card OK; cable card -> Cancel
    hn.answers.rules.clear()
    a.start_bandwidth()                                                   # OK, OK: the pilot point, then 'First-point validation'
    pump(hn, a)
    a.start_bandwidth()                                                   # continue with the remaining 23 points
    pump(hn, a, limit=6000)
    a.start_bandwidth()                                                   # 'Complete'
    a.bw_batch = True
    a.bw_running = False
    a.next_bandwidth()                                                    # 'Bandwidth complete'
    a.bw_tree.selection.return_value = ('i1',)
    a.bw_tree.index.return_value = 2
    rule(hn, title_is('Confirm bandwidth retest'))
    a.retest_bandwidth()                                                  # -> Cancel
    hn.answers.rules.clear()
    a.bw_settle.set('0')
    a.retest_bandwidth()                                                  # card -> OK, then 'Settings'
    a.bw_settle.set('3.0')
    a.retest_bandwidth()                                                  # card -> OK, runs
    pump(hn, a)
    a.events.put(('bw_error', 'P1 PkPk failed'))
    a.events.put(('bw_safety', 'Fluke standby not confirmed'))
    pump(hn, a)                                                           # 'Bandwidth error' / 'Fluke output safety'

    # time base
    a.tb_running = True
    a.start_timebase()                                                    # 'Busy'
    a.tb_running = False
    a.tb_settle.set('99')
    a.start_timebase()                                                    # 'Time base settings'
    a.tb_settle.set('3.0')
    rule(hn, title_is('Time base accuracy'))
    a.start_timebase()                                                    # -> Cancel
    hn.answers.rules.clear()
    a.start_timebase()                                                    # -> OK, the point runs
    pump(hn, a)
    a.start_timebase()                                                    # 'Complete'
    a.tb_tree.selection.return_value = ('i0',)
    a.tb_tree.index.return_value = 0
    rule(hn, title_is('Confirm time base retest'))
    a.retest_timebase()                                                   # -> Cancel
    hn.answers.rules.clear()
    a.retest_timebase()                                                   # -> OK, runs
    pump(hn, a)
    a.events.put(('tb_error', 'marker rejected'))
    a.events.put(('tb_safety', 'Fluke standby not confirmed'))
    pump(hn, a)                                                           # 'Time base error' / 'Fluke output safety'

    # trigger level
    a.trig_running = True
    a.start_trigger()                                                     # 'Busy'
    a.trig_running = False
    a.trig_settle.set('99')
    a.start_trigger()                                                     # 'Trigger level settings'
    a.trig_settle.set('1.0')
    rule(hn, title_is('Trigger level test method'))
    a.start_trigger()                                                     # -> Cancel
    hn.answers.rules.clear()
    rule(hn, title_is('Trigger level cable connection'))
    a.start_trigger()                                                     # method card OK; cable card -> Cancel
    hn.answers.rules.clear()
    rule(hn, lambda r: None if r['kind'] != 'ask_yes_no_cancel' else False)
    a.start_trigger()                                                     # OK, OK; every point asks 'did it trigger?' (No)
    pump(hn, a, limit=6000)
    a.start_trigger()                                                     # 'Complete'
    a.trig_batch = True
    a.trig_running = False
    a.next_trigger()                                                      # 'Complete'
    a.trig_tree.selection.return_value = ('i1',)
    a.trig_tree.index.return_value = 2
    rule(hn, title_is('Confirm trigger level retest'))
    a.retest_trigger()                                                    # -> Cancel
    hn.answers.rules.clear()
    a.trig_settle.set('0')
    a.retest_trigger()                                                    # 'Trigger level settings' (before the card)
    a.trig_settle.set('1.0')
    a.retest_trigger()                                                    # card -> OK, runs
    pump(hn, a)
    a.events.put(('trig_error', 'trigger did not arm'))
    a.events.put(('trig_safety', 'Fluke standby not confirmed'))
    a.events.put(('trig_cancel', 'Point abandoned'))
    pump(hn, a)                                                           # 'Trigger level error' / 'Fluke output safety'
    done('sections', hn)

    # 5b. saved results that do not match the procedure: the warning of each section's checkpoint loader
    hn, a = new()
    for attr, loader in (('offset_checkpoint', a.load_offset_checkpoint), ('bw_checkpoint', a.load_bandwidth_checkpoint), ('tb_checkpoint', a.load_timebase_checkpoint),
                         ('trig_checkpoint', a.load_trigger_checkpoint)):
        getattr(a, attr).write_text('[1]', encoding='utf-8')
        loader()
    done('bad_checkpoints', hn)

    # 6. the exports (fake report writers, nothing is written) and the dialogs of closing the window
    import report_pdf
    hn, a = new()
    with mock.patch.object(report_pdf, 'write_calibration_pdf', lambda filename, rows, **k: len(rows)):
        a.export_pdf_report()                                             # nothing recorded -> info
        a.export_professional_excel()                                     # nothing recorded -> info
        a.export_calibration_section('dcv')                               # nothing recorded -> info
        a.write_certificate_pdf('x.pdf', [])                              # nothing recorded -> info
        a.load_demo_data()
        a.export_pdf_report()                                              # report details cancelled
        a.export_calibration_section('dcv')                               # report details cancelled
        rule(hn, lambda r: {} if r['kind'] == 'report_details' else None)
        a.export_pdf_report()                                              # details given, save-as cancelled
        a.export_calibration_section('noise')                             # details given, save-as cancelled
        a.export_professional_excel()                                     # save-as cancelled
        hn.answers.save_path = 'Calibration Data WS-1.pdf'
        a.export_pdf_report()                                              # 'Report exported'
        a.export_calibration_section('trigger')                           # 'Report exported'
        with mock.patch.object(report_pdf, 'write_calibration_pdf', side_effect=RuntimeError('disk full')):
            a.export_pdf_report()                                          # 'PDF export error'
        with mock.patch.object(report_pdf, 'write_calibration_pdf', side_effect=ImportError('reportlab')):
            a.export_pdf_report()                                          # 'PDF export dependency'
        hn.answers.save_path = 'Calibration Data WS-1.xlsx'
        with mock.patch.object(W, 'make_report', lambda groups, filename, **k: 7):
            a.export_professional_excel()                                  # 'Report exported'
        with mock.patch.object(W, 'make_report', side_effect=RuntimeError('locked')):
            a.export_professional_excel()                                  # 'Excel export error'
        with mock.patch.object(W, 'make_report', side_effect=ImportError('openpyxl')):
            a.export_professional_excel()                                  # 'Excel export dependency'
        hn.answers.rules.clear()
    done('exports', hn)

    hn, a = new()
    for flag, label in (('tb_running', 'tb'), ('trig_running', 'trig'), ('bw_running', 'bw'), ('offset_running', 'offset'), ('imp_running', 'imp'),
                        ('dc_running', 'dc')):
        setattr(a, flag, True)
        a.on_close()                                                      # one warning per running measurement
        setattr(a, flag, False)
    a.running = True
    rule(hn, title_is('Test running'))
    a.on_close()                                                          # 'Stop the test and close the window?' -> No
    hn.answers.rules.clear()
    done('close_window', hn)
    return out
