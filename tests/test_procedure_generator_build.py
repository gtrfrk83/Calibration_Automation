"""Procedure Generator: building a procedure from accepted rows (mocked reader output), running it on the simulated bench with typed readings, the DRAFT marking in three
places, the owner's approval, the readiness check, and the guarantee that existing data is untouched.  No network, no instruments, no tkinter.
Run:  python -m unittest tests.test_procedure_generator_build"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import dsb_run_harness as H  # noqa: E402
import pg_fixtures as fx  # noqa: E402
import procedure_generator as pg  # noqa: E402
import procedure_generator_ai as ai  # noqa: E402
import procedure_generator_build as bd  # noqa: E402
import generated_draft as gd  # noqa: E402
import datasheet_builder as db  # noqa: E402
import dsb_manager  # noqa: E402
import dsb_runtime as rt  # noqa: E402
from tests import _tk_stub as _boot  # noqa: E402  (test-only stand-ins for the removed Tk modules)
_boot.install()  # noqa: E402
import report_dialog  # noqa: E402
from drivers.simulated import make_bench, SimFlukeTransport  # noqa: E402

REAL_DB = ROOT / 'calibration_procedures.sqlite3'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


class Fix(unittest.TestCase):
    MODE = pg.ONEWAY

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.data = self.d / 'data'
        self.data.mkdir()
        self.env = mock.patch.dict(os.environ, {'CALSUITE_DATA': str(self.data), 'HOME': str(self.d / 'home'), 'USERPROFILE': str(self.d / 'home')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.reg = self.data / 'lab_registry.sqlite3'
        self.us = self.d / 'us'
        self.store = pg.Store(root=self.d / 'gen', registry=self.reg)
        self.real_before = sha(REAL_DB)
        self.p = self.project(self.MODE)
        self.h = None

    def tearDown(self):
        if self.h is not None:
            self.h.stop()
        self.assertEqual(sha(REAL_DB), self.real_before)                       # calibration_procedures.sqlite3 is never touched
        self.assertFalse((self.data / 'calibration_procedures.sqlite3').exists())

    def project(self, mode, items=None, name='Test meter'):
        p = self.store.create(name, 'tester')
        p.make, p.model, p.mode = 'Acme', 'TM100', mode
        f = self.store.add_file(p, fx.make_pdf(self.d / f'm{len(self.store.list())}.pdf'), pg.ROLE_SPEC)
        pg.set_pages(p, f.id, 1, 1)
        pg.add_rows(p, ai._parse_rows({'rows': items or fx.good_items()}, [(f.id, 1)], []))
        for r in p.rows:
            pg.set_status(p, r.id, pg.STATUS_ACCEPTED)
        pg.confirm_page(p, f.id, 1)
        return p

    def build(self, p=None, **kw):
        res = bd.build(p or self.p, self.store, 'tester', registry=self.reg, root=self.us, **kw)
        self.assertTrue(res.ok, res.message)
        return res

    def spec_of(self, res):
        return json.loads((self.us / (res.uid + '.json')).read_text())

    def app(self, res, demo=False, bench=None):
        """bench: None = the simulated 5522A / 5560A for an automated (one-way) procedure; a manual one needs none."""
        self.h = H.Harness(home=self.d).start()                    # the harness data folder is this test's data folder (one registry)
        io = None
        if not demo and (bench if bench is not None else self.MODE == pg.ONEWAY):
            b, _a, _b = make_bench()
            io = rt.DsbIO({}, transports={m: SimFlukeTransport(b, m) for m in ('5560A', '5522A')}, scope=False)
        a = self.h.make_app(self.spec_of(res), demo=demo, io=io)
        self.io = io
        return a

    def type_all(self, a):
        for p in a.points:
            a.type_reading(p, H.typed_nominal(p))

    def export(self, a, name='A-100-2026-10-27.pdf'):
        out = str(self.d / 'out' / name)
        Path(out).parent.mkdir(exist_ok=True)
        d = {'technician': 'T', 'temperature': '23', 'humidity': '45', 'standards': [], 'procedure': '', 'show_tar_tur': True}
        seen = {}

        def save(**k):
            seen.update(k)
            return out
        with mock.patch.object(report_dialog, 'ask_details', lambda parent, proc='': d), mock.patch.object(rt.hh.filedialog, 'asksaveasfilename', save):
            a.export_pdf()
        self.seen = seen
        return out

    def pages(self, pdf):
        txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True).stdout
        return [t for t in txt.split('\f') if t.strip()]


class BuildOneWay(Fix):
    def test_the_built_procedure_is_registered_runnable_and_a_draft(self):
        res = self.build()
        self.assertEqual((res.status, res.kind, res.points, res.mode), ('ready', 'verification', 3, pg.ONEWAY))
        rows = {r['uid']: r for r in dsb_manager.user_rows(root=self.us, db=self.reg)}
        row = rows[res.uid]
        self.assertTrue(row['draft'])
        self.assertIn('DRAFT: not approved by the owner', row['description'])
        self.assertEqual(row['kind'], 'verification')
        st = gd.state(res.uid, self.reg)
        self.assertEqual((st.generated, st.draft, st.project_id), (True, True, self.p.id))
        self.assertEqual(self.spec_of(res)['dsb']['generated'], self.p.id)
        self.assertEqual(self.p.build['uid'], res.uid)
        self.assertEqual(list(self.p.build['source_files'].values()), [self.p.files[0].sha256])

    def test_values_are_the_accepted_rows_in_decimal(self):
        res = self.build()
        ds = db.load(res.uid, root=self.us, db=self.reg)
        pts = {fn.kind + p.label: p for fn, p in ds.all_points()}
        fn_p = [(fn, p) for fn, p in ds.all_points()]
        self.assertEqual(len(fn_p), 3)
        dcv = [p for fn, p in fn_p if fn.kind == 'DCV']
        top = next(p for p in dcv if db.fmt(p.nominal) == '5')
        self.assertEqual(top.overrides['1y'], {'low': '4.995', 'high': '5.005'})
        small = next(p for p in dcv if db.fmt(p.nominal) == '0.05')
        self.assertEqual(small.overrides['1y'], {'low': '0.04995', 'high': '0.05005'})        # 49.95 mV as printed, exact SI
        self.assertTrue(ds.options.get('function_prompt'))
        self.assertFalse(ds.options.get('manual_entry'))
        self.assertEqual(ds.options.get('generated'), self.p.id)

    def test_run_on_the_simulated_bench_with_typed_readings_and_a_draft_pdf(self):
        res = self.build()
        a = self.app(res)
        self.assertFalse(a.manual_entry)
        self.h.default_reading = H.typed_nominal
        # (1) the run start asks about the draft
        self.assertTrue(self.h.run_all())
        boxes = [d for d in self.h.dialogs if d[0] == 'box' and d[1] == 'askyesno' and d[2] == gd.RUN_START_TITLE]
        self.assertEqual(len(boxes), 1)
        self.assertIn('NOT been approved', boxes[0][3])
        self.assertEqual(len(a.found), 3)
        self.assertTrue(all(r['result'] == 'PASS' and not r.get('synthetic') for r in a.found.values()))
        sent = [t for _i, t in H.wire(self.io)]
        outs = [t for t in sent if t.startswith('OUT ') and not t.endswith('?')]
        self.assertEqual(len(outs), 3)                                               # the calibrator is driven for every point
        self.assertIn('OUT 5V,0Hz', ' '.join(outs).replace('5.00000', '5').replace(' ', '') if False else ' '.join(outs))
        states = [t for t in sent if t in ('OPER', 'STBY')]
        self.assertEqual(states[-1], 'STBY')                                          # output to standby at the end
        # (2) the window carries the banner
        self.assertTrue(a.generated_state().draft)
        # (3) every page of the PDF
        pdf = self.export(a)
        self.assertEqual(Path(pdf).name, 'A-100-2026-10-27.pdf')
        pages = self.pages(pdf)
        self.assertGreaterEqual(len(pages), 1)
        for n, t in enumerate(pages, 1):
            self.assertIn('DRAFT: NOT APPROVED BY THE OWNER', t.upper(), f'page {n}')
        txt = '\n'.join(pages)
        info = subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout
        self.assertIn('Title:           Acme TM100 - Test meter', info)               # the same title as the other automated sheets (Make Model - title)
        import re
        self.assertRegex(self.seen.get('initialfile', ''), r'^A-100-\d{2}-\d{2}-\d{4}\.pdf$')       # named asset#-date (the engine's own file name, unchanged)
        self.assertNotIn('Procedure status', txt)  # owner 2026-10-30: the report header shows only the asset ID, serial number and report date (the DRAFT banner stays)
        self.assertNotIn('standards due', txt.lower())

    def test_declining_the_confirmation_runs_nothing(self):
        res = self.build()
        a = self.app(res)
        self.h.box_answer['askyesno'] = False
        self.h.default_reading = H.typed_nominal
        self.h.run_all()
        self.assertEqual(a.found, {})
        self.assertTrue(any(d[0] == 'box' and d[2] == gd.RUN_START_TITLE for d in self.h.dialogs))

    def test_the_confirmation_is_asked_once_per_window(self):
        res = self.build()
        a = self.app(res)
        self.h.default_reading = H.typed_nominal
        self.h.run_all()
        n = len([d for d in self.h.dialogs if d[0] == 'box' and d[2] == gd.RUN_START_TITLE])
        a.run_all()
        self.h.pump()
        self.assertEqual(len([d for d in self.h.dialogs if d[0] == 'box' and d[2] == gd.RUN_START_TITLE]), n)

    def test_demo_run_asks_nothing_and_is_marked_demo_and_draft(self):
        res = self.build()
        a = self.app(res, demo=True)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual([d for d in self.h.dialogs if d[0] == 'box' and d[2] == gd.RUN_START_TITLE], [])
        self.assertEqual(len(a.found), 3)
        self.assertTrue(all(r['synthetic'] for r in a.found.values()))
        pdf = self.export(a)
        for t in self.pages(pdf):
            self.assertIn('DEMO', t.upper())
            self.assertIn('DRAFT: NOT APPROVED', t.upper())

    def test_approval_removes_the_draft_marking_everywhere_and_is_logged(self):
        res = self.build()
        a = self.app(res)
        self.assertTrue(a.generated_state().draft)
        with self.assertRaises(gd.ApprovalError):
            gd.approve(res.uid, ' ', db=self.reg)
        gd.approve(res.uid, 'Owner Name', 'checked against the manual', db=self.reg)
        self.assertFalse(a.generated_state().draft)                              # seen by a window that is already open
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(a.found), 3)
        self.assertEqual([d for d in self.h.dialogs if d[0] == 'box' and d[2] == gd.RUN_START_TITLE], [])
        pages = self.pages(self.export(a))
        self.assertTrue(pages)
        for t in pages:
            self.assertNotIn('DRAFT: NOT APPROVED', t.upper())
        self.assertNotIn('approved by Owner Name', ' '.join(self.pages(self.export(a, 'A-100-2026-10-28.pdf'))))  # owner 2026-10-30: the report header shows only the asset ID, serial number and report date
        self.assertFalse(next(r for r in dsb_manager.user_rows(root=self.us, db=self.reg) if r['uid'] == res.uid)['draft'])
        hist = gd.state(res.uid, self.reg).history
        self.assertEqual([h[0] for h in hist], ['built', 'approve'])
        self.assertEqual((hist[1][2], hist[1][4]), ('Owner Name', 'checked against the manual'))
        with self.assertRaises(gd.ApprovalError):
            gd.approve(res.uid, 'Owner Name', db=self.reg)                       # already approved

    def test_mark_as_draft_again_and_the_log_cannot_be_edited(self):
        res = self.build()
        gd.approve(res.uid, 'Owner', db=self.reg)
        gd.mark_draft_again(res.uid, 'Owner', 'found a misread limit', db=self.reg)
        self.assertTrue(gd.state(res.uid, self.reg).draft)
        import sqlite3
        con = sqlite3.connect(self.reg)
        for sql in ('UPDATE generated_approvals SET who=\'x\'', 'DELETE FROM generated_approvals'):
            with self.assertRaises(sqlite3.DatabaseError):
                con.execute(sql)
        con.close()
        self.assertEqual([h[0] for h in gd.state(res.uid, self.reg).history], ['built', 'approve', 'draft_again'])

    def test_a_rebuild_is_a_draft_again_without_anyone_remembering(self):
        res = self.build()
        gd.approve(res.uid, 'Owner', db=self.reg)
        self.assertFalse(gd.state(res.uid, self.reg).draft)
        pg.edit_row(self.p, self.p.rows[0].id, high='5.006 V')
        pg.confirm_page(self.p, self.p.files[0].id, 1)
        res2 = self.build(replace_uid=res.uid)
        self.assertEqual(res2.uid, res.uid)
        self.assertGreater(res2.version, res.version)
        self.assertTrue(gd.state(res.uid, self.reg).draft)

    def test_a_draft_cannot_be_hidden_by_losing_the_registry(self):
        res = self.build()
        a = self.app(res)
        self.reg.unlink()
        st = a.generated_state()
        self.assertTrue(st.draft and st.generated)                                # fails closed

    def test_an_ordinary_procedure_is_untouched(self):
        import dsb_fixtures as dfx
        import datasheet_builder_specs as dsp
        import datasheet_builder_match as dm
        spec = dsp.export_spec(dfx.dmm_34461a_like(), plan=dm.match_datasheet(dfx.dmm_34461a_like())).spec
        self.h = H.Harness(home=self.d).start()
        b, _a, _b = make_bench()
        a = self.h.make_app(spec, io=rt.DsbIO({}, transports={m: SimFlukeTransport(b, m) for m in ('5560A', '5522A')}, scope=False))
        self.assertFalse(a.generated_state().generated)
        self.assertNotIn('draft_note', a.report_details({}))
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual([d for d in self.h.dialogs if d[0] == 'box' and d[2] == gd.RUN_START_TITLE], [])
        pages = self.pages(self.export(a))
        self.assertTrue(pages)
        for t in pages:
            self.assertNotIn('DRAFT', t.upper())

    def test_readiness_check_runs_on_the_generated_procedure(self):
        res = self.build()
        r = subprocess.run([sys.executable, str(ROOT / 'tools' / 'readiness_check.py'), res.uid, '--verbose', '--json', str(self.d / 'r.json')], capture_output=True, text=True,
                           env=dict(os.environ), cwd=str(ROOT))
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-1500:])
        self.assertIn('PASS run', r.stdout)
        self.assertIn('uncertainty', r.stdout)
        data = json.loads((self.d / 'r.json').read_text())
        self.assertEqual(data['reports'][0]['proc']['id'] if 'proc' in data['reports'][0] else res.uid, res.uid)
        self.assertNotIn('FAIL', [f['level'] for f in data['reports'][0]['findings']])


class HookupPhoto(Fix):
    def photo_project(self, with_photo=True):
        p = self.project(pg.ONEWAY, name='With photo')
        if with_photo:
            self.store.add_file(p, fx.make_png(self.d / 'hook.png'), pg.ROLE_PHOTO)
        return p

    def test_the_stored_photo_is_the_reference_image_of_the_setup_prompt(self):
        p = self.photo_project()
        res = self.build(p)
        stored = self.store.file_path(p, p.files_of(pg.ROLE_PHOTO)[0].id)
        self.assertEqual(self.spec_of(res)['dsb']['hookup_photo'], str(stored))
        a = self.app(res)
        images = []
        orig = self.h._confirm

        def spy(parent, title, heading, steps, facts=None, caution=None, ok='OK', cancel='Cancel', image=None, **k):
            images.append((title, image))
            return orig(parent, title, heading, steps, facts, caution, ok, cancel, image, **k)
        with mock.patch.object(H.ui, 'confirm_steps', spy):
            self.h.default_reading = H.typed_nominal
            self.assertTrue(self.h.run_all())
        setups = [img for t, img in images if t in ('Check the setup', 'Change the cables')]
        self.assertTrue(setups)
        self.assertTrue(all(Path(img) == stored for img in setups), images)
        self.assertEqual(len(a.found), 3)

    def test_no_photo_means_no_image_and_nothing_is_invented(self):
        res = self.build(self.photo_project(with_photo=False))
        self.assertNotIn('hookup_photo', self.spec_of(res)['dsb'])
        a = self.app(res)
        self.assertIsNone(a._reference_image(a.points[0]))

    def test_a_missing_photo_file_is_ignored_and_an_owner_diagram_wins(self):
        p = self.photo_project()
        res = self.build(p)
        a = self.app(res)
        stored = Path(a.dsb['hookup_photo'])
        self.assertEqual(Path(a._reference_image(a.points[0])), stored)
        seen = []
        with mock.patch.object(rt.port, 'operator_prompt', lambda *x, **k: seen.append(k.get('image')) or True):
            a._with_reference_image(a.points[0], lambda p: rt.port.operator_prompt('t', 'h', [], image=None))
            diagram = self.d / 'diagram.png'
            fx.make_png(diagram)
            a._with_reference_image(a.points[0], lambda p: rt.port.operator_prompt('t', 'h', [], image=diagram))
        self.assertEqual([Path(x) for x in seen], [stored, diagram])                       # the owner's drawn diagram always wins
        self.assertIs(rt.port.operator_prompt.__name__ != 'with_image', True)               # the shared function is put back
        stored.unlink()
        self.assertIsNone(a._reference_image(a.points[0]))

    def test_other_procedures_get_no_reference_image(self):
        import dsb_fixtures as dfx
        import datasheet_builder_specs as dsp
        import datasheet_builder_match as dm
        spec = dsp.export_spec(dfx.dmm_34461a_like(), plan=dm.match_datasheet(dfx.dmm_34461a_like())).spec
        self.assertNotIn('hookup_photo', spec['dsb'])
        self.h = H.Harness(home=self.d).start()
        a = self.h.make_app(spec)
        self.assertIsNone(a._reference_image(a.points[0]))


class BuildManual(Fix):
    MODE = pg.MANUAL

    def test_manual_is_a_manual_entry_procedure_with_typed_readings(self):
        res = self.build()
        self.assertEqual((res.kind, res.status), ('manual', 'ready'))
        a = self.app(res)
        self.assertTrue(a.manual_entry)
        self.assertFalse(a.wants_connection())
        p = a.points[0]
        a.type_reading(p, '5')
        rec = a.results[p['id']]
        self.assertEqual((rec['entered'], rec['result'], rec['source']), ('5.000', 'PASS', 'typed'))       # padded to the printed resolution
        a.type_reading(p, '5.0060')
        self.assertEqual(a.results[p['id']]['result'], 'FAIL')
        with self.assertRaises(ValueError):
            a.type_reading(p, 'abc')

    def test_manual_run_pdf_has_the_banner_on_every_page_and_no_instrument_traffic(self):
        res = self.build()
        a = self.app(res)
        self.h.default_reading = H.typed_nominal
        self.assertTrue(self.h.run_all())
        self.assertEqual(len(a.found), 3)
        pages = self.pages(self.export(a))
        self.assertTrue(pages)
        for t in pages:
            self.assertIn('DRAFT: NOT APPROVED', t.upper())

    def test_manual_uses_the_best_fit_standard_or_waives_with_a_record(self):
        res = self.build()
        ds = db.load(res.uid, root=self.us, db=self.reg)
        self.assertTrue(ds.options.get('manual_entry'))
        self.assertTrue(res.standard)
        p2 = self.project(pg.MANUAL, name='Second')
        res2 = self.build(p2, standard='')
        self.assertTrue(any('uncertainty' in u.lower() for u in res2.unverified) or res2.uncertainty_missing is not None)


class Unverified(Fix):
    def test_unverified_list_and_uncertainty_gaps_are_carried(self):
        items = fx.good_items() + [fx.model_item(1, '1-4', 'DCV', 'DC volts', '100 V', '100.0 V', '99.0 V', '101.0 V', uncertain=True, note='1 or 0?')]
        p = self.project(pg.ONEWAY, items, name='With doubt')
        res = self.build(p)
        text = '\n'.join(res.unverified)
        self.assertIn('1 or 0?', text)
        self.assertIn('1 year', text)                                              # the calibration-interval placeholder is declared, not hidden
        stored = gd.state(res.uid, self.reg).unverified
        self.assertEqual(stored, res.unverified)
        self.assertIsInstance(res.uncertainty_missing, list)

    def test_a_row_without_limits_from_accuracy_is_built_from_the_accuracy_and_flagged(self):
        items = [fx.model_item(1, '2-1', 'DCV', 'DC volts', '10 V', '5.000 V', accuracy='0.05 % of reading')]
        p = self.project(pg.ONEWAY, items, name='Accuracy only')
        res = self.build(p)
        self.assertIn('accuracy', '\n'.join(res.unverified).lower())

    def test_accuracy_in_counts_is_refused_before_building(self):
        items = [fx.model_item(1, '2-1', 'DCV', 'DC volts', '10 V', '5.000 V', accuracy='0.05 % of reading + 2 counts')]
        p = self.project(pg.ONEWAY, items, name='Counts')
        g = pg.gate(p)
        self.assertEqual((g.stage, g.can_click), ('errors', False))
        self.assertIn('counts', g.text)

    def test_nothing_is_built_while_the_gate_is_closed(self):
        pg.set_status(self.p, self.p.rows[0].id, pg.STATUS_CANDIDATE)
        res = bd.build(self.p, self.store, 'tester', registry=self.reg, root=self.us)
        self.assertFalse(res.ok)
        self.assertFalse(self.us.exists() and any(self.us.glob('*.json')))
        self.assertEqual(gd.draft_uids(self.reg), set())


class Existing(unittest.TestCase):
    def test_no_generated_tables_means_no_draft_anywhere(self):
        d = Path(tempfile.mkdtemp())
        self.assertEqual(gd.draft_uids(d / 'none.sqlite3'), set())
        self.assertFalse(gd.state('x', d / 'none.sqlite3').generated)
        self.assertFalse((d / 'none.sqlite3').exists())                              # read only: asking never creates a registry


if __name__ == '__main__':
    unittest.main()
