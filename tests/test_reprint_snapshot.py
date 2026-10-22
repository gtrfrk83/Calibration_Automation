"""report_snapshot.py: saving at issue time, hash verification, old events, demo, damaged databases, the regenerate flow.  No tkinter, no instruments.

File name sorts after test_beta (see test_reprint_roundtrip.py).  Run:  python -m unittest tests.test_reprint_snapshot
"""
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import reprint_harness as R  # noqa: E402
import labregistry  # noqa: E402
import report_pdf  # noqa: E402
import report_snapshot as rs  # noqa: E402

try:
    import reportlab  # noqa: F401
    import pypdf  # noqa: F401
    HAVE = True
except Exception:
    HAVE = False

HEADER = [('Instrument', 'Test DMM'), ('Instrument ID', 'A-7'), ('Serial', 'SN7'), ('Source', 'A manual, p. 1')]
LATER = datetime(2026, 10, 22, 9, 30)


def rows():
    return [
        report_pdf.cert_row('10 V range', 10, 9.9990, 10.0010, 'V', reading=10.0002, section='DC Volts', uncertainty='12 µV/V'),
        report_pdf.cert_row('100 V range', 100, 99.99, 100.01, 'V', reading=100.02, failed=True, section='DC Volts', uncertainty='20 µV/V'),
        report_pdf.cert_row('1 kΩ', 1000, 999.5, 1000.5, 'ohm', reading=1000.1, section='Resistance'),
    ]


def issue(path, **kw):
    kw.setdefault('details', dict(R.DETAILS))
    kw.setdefault('footer_note', 'Uncertainty from the A2LA scope.')
    return report_pdf.write_calibration_pdf(str(path), rows(), header=kw.pop('header', HEADER), **kw)


def asking(path, over=False):
    log = []

    def choose(name, original):
        log.append(('choose', name, original))
        return path

    def overwrite(p, is_original):
        log.append(('overwrite', p, is_original))
        return over
    return choose, overwrite, log


@unittest.skipUnless(HAVE, 'reportlab is not installed')
class Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        ctx = R.registry()
        self.db = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def n_snapshots(self):
        with rs._db() as con:
            return con.execute('SELECT COUNT(*) FROM report_snapshots').fetchone()[0]

    def edit(self, sql, *args):
        con = sqlite3.connect(str(self.db))
        con.execute(sql, args)
        con.commit()
        con.close()


class Saving(Base):
    def test_issue_saves_a_complete_snapshot_linked_to_the_history_event(self):
        issue(self.dir / 'a.pdf', show_tar_tur=report_pdf.TarTur(True, False), snapshot_context={'suite': {'version': 'v-test'}})
        rid = labregistry.runs_for('A-7')[0]['id']
        got = rs.load(rid)
        self.assertEqual(got.status, rs.OK, got.message)
        d = got.data
        self.assertEqual(d['header'][1], ['Instrument ID', 'A-7'])
        self.assertEqual(d['title'], 'Calibration Data')
        self.assertEqual(d['issued_at'], '2026-01-02 03:04')
        self.assertEqual(d['details']['technician'], 'T. Tech')
        self.assertEqual(d['details']['standards'][0]['due'], '2027-01-01')
        self.assertEqual(d['footer_note'], 'Uncertainty from the A2LA scope.')
        self.assertEqual(d['show_tar_tur'], {'__tar_tur__': [True, False]})
        self.assertEqual([r['Description'] for r in d['rows']], [r['Description'] for r in rows()])
        self.assertEqual(d['rows'][1]['OOT'], 'OOT')
        self.assertEqual(d['stamps'], {'suite': {'version': 'v-test'}})
        self.assertFalse(d['demo'])
        self.assertEqual(len(d['content_sha256']), 64)

    def test_row_text_is_stored_exactly_as_printed(self):
        issue(self.dir / 'a.pdf')
        d = rs.load(labregistry.runs_for('A-7')[0]['id']).data
        self.assertEqual(d['rows'], json.loads(json.dumps(rows())))

    def test_demo_is_never_snapshotted(self):
        issue(self.dir / 'd.pdf', demo=True)
        self.assertEqual(labregistry.runs_for('A-7'), [])
        self.assertEqual(self.n_snapshots(), 0)
        self.assertFalse(rs.record_issued(1, header=HEADER, rows=rows(), demo=True))
        self.assertEqual(self.n_snapshots(), 0)

    def test_a_snapshot_marked_demo_is_refused(self):
        issue(self.dir / 'a.pdf')
        rid = labregistry.runs_for('A-7')[0]['id']
        data = rs.load(rid).data
        data.pop('content_sha256')
        data['demo'] = True
        text = rs.canon(data)
        self.edit('UPDATE report_snapshots SET payload_json=?, sha256=?', text, rs.sha(text))      # even with a valid checksum
        self.assertEqual(rs.load(rid).status, rs.DEMO)
        self.assertEqual(rs.plan(rid).kind, rs.NONE)

    def test_no_instrument_id_means_no_event_and_no_snapshot(self):
        issue(self.dir / 'n.pdf', header=[('Instrument', 'X'), ('Instrument ID', 'NOT ENTERED')])
        self.assertEqual(self.n_snapshots(), 0)

    def test_exporting_again_to_the_same_file_replaces_event_and_snapshot(self):
        issue(self.dir / 'a.pdf')
        issue(self.dir / 'a.pdf')
        self.assertEqual(len(labregistry.runs_for('A-7')), 1)
        self.assertEqual(self.n_snapshots(), 1)

    def test_data_that_cannot_be_stored_exactly_saves_nothing_and_the_pdf_still_prints(self):
        n = issue(self.dir / 'a.pdf', details={'technician': 'T', 'odd': object()})
        self.assertEqual(n, 3)
        self.assertEqual(self.n_snapshots(), 0)
        self.assertEqual(len(labregistry.runs_for('A-7')), 1)
        self.assertFalse(rs.record_issued(1, header=HEADER, rows=[{'x': float('nan')}]))

    def test_snapshot_context_and_event_changes_do_not_change_the_pdf_bytes(self):
        issue(self.dir / 'a.pdf')
        issue(self.dir / 'b.pdf', snapshot_context={'x': 1}, record_history=False)
        self.assertEqual((self.dir / 'a.pdf').read_bytes(), (self.dir / 'b.pdf').read_bytes())

    def test_unmodified_pdf_is_byte_identical_to_origin_main(self):
        src = subprocess.run(['git', 'show', 'origin/main:report_pdf.py'], cwd=ROOT, capture_output=True, text=True)
        if src.returncode:
            self.skipTest('git baseline unavailable')
        p = self.dir / 'report_pdf_baseline.py'
        p.write_text(src.stdout, encoding='utf-8')
        spec = importlib.util.spec_from_file_location('report_pdf_baseline', p)
        base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(base)
        with mock.patch.object(base, 'datetime', R.Clock):
            base.write_calibration_pdf(str(self.dir / 'old.pdf'), rows(), header=HEADER, details=dict(R.DETAILS), footer_note='n')
        issue(self.dir / 'new.pdf', footer_note='n')
        self.assertEqual((self.dir / 'old.pdf').read_bytes(), (self.dir / 'new.pdf').read_bytes())


class Verification(Base):
    def setUp(self):
        super().setUp()
        issue(self.dir / 'a.pdf')
        self.rid = labregistry.runs_for('A-7')[0]['id']

    def test_changed_payload_is_refused_and_nothing_is_written(self):
        self.edit("UPDATE report_snapshots SET payload_json=replace(payload_json,'T. Tech','Someone Else')")
        self.assertEqual(rs.load(self.rid).status, rs.MISMATCH)
        choose, overwrite, log = asking(self.dir / 'out.pdf')
        res = rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite)
        self.assertFalse(res.ok)
        self.assertIn('checksum', res.message)
        self.assertEqual(log, [], 'refused before asking where to save')
        self.assertFalse((self.dir / 'out.pdf').exists())

    def test_a_checksum_mismatch_is_not_replaced_by_a_rebuild_from_history(self):
        self.edit("UPDATE report_snapshots SET sha256='0'*0 || 'deadbeef'")
        self.assertEqual(rs.plan(self.rid).kind, rs.NONE)

    def test_snapshot_of_another_asset_is_refused(self):
        self.edit("UPDATE runs SET asset_id='OTHER'")
        self.assertEqual(rs.load(self.rid).status, rs.UNLINKED)

    def test_unknown_format_or_schema_is_refused(self):
        d = rs.load(self.rid).data
        d.pop('content_sha256')
        d['schema'] = 99
        text = rs.canon(d)
        self.edit('UPDATE report_snapshots SET payload_json=?, sha256=?', text, rs.sha(text))
        self.assertEqual(rs.load(self.rid).status, rs.DAMAGED)

    def test_garbage_payload_with_a_matching_checksum_is_damaged(self):
        self.edit('UPDATE report_snapshots SET payload_json=?, sha256=?', 'not json', rs.sha('not json'))
        self.assertEqual(rs.load(self.rid).status, rs.DAMAGED)


class OldEvents(Base):
    """An event issued before snapshots existed: only the history rows (runs / points) are there."""

    def setUp(self):
        super().setUp()
        issue(self.dir / 'a.pdf', details=dict(R.DETAILS, procedure='Test DMM performance verification'))
        self.rid = labregistry.runs_for('A-7')[0]['id']
        self.edit('DELETE FROM report_snapshots')

    def test_missing_snapshot_message(self):
        got = rs.load(self.rid)
        self.assertEqual(got.status, rs.MISSING)
        self.assertIn('no saved report record', got.message)

    def test_complete_history_rows_offer_a_clearly_marked_rebuild(self):
        pl = rs.plan(self.rid)
        self.assertEqual(pl.kind, rs.REBUILT)
        self.assertIn('NOT be identical', pl.message)
        for lack in ('As Left readings', 'uncertainty values', 'TAR / TUR'):
            self.assertIn(lack, pl.message)
        self.assertEqual(rs.availability(self.rid)[0], rs.REBUILT)
        out = self.dir / 'rebuilt.pdf'
        choose, overwrite, _ = asking(out)
        asked = []
        res = rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite, confirm_rebuilt=lambda m: asked.append(m) or True, now=LATER)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.kind, rs.REBUILT)
        self.assertEqual(len(asked), 1)
        text = R.pdf_text(out)
        self.assertIn('REBUILT 2026-10-22 from history rows, no original snapshot', text)
        for desc in ('10 V range', '100 V range', '1 kOhm'):       # report_pdf spells ohms 'Ohm' in the description column
            self.assertIn(desc, text)
        self.assertIn('RESULT: OUT OF TOLERANCE', text)
        self.assertNotIn('Same', text, 'As Left is not stored, so nothing is claimed about it')
        self.assertNotIn('N/A', text)

    def test_rebuilt_values_come_only_from_the_stored_rows(self):
        data, run, problem = rs.rebuild_from_history(self.rid)
        self.assertEqual(problem, '')
        original = rows()
        for got, want in zip(data['rows'], original):
            for key in ('Section', 'Description', 'Nominal', 'Tolerance -', 'Tolerance +', 'UOM', 'As Found', 'OOT'):
                self.assertEqual(got[key], want[key], key)
            self.assertEqual((got['As Left'], got['Uncertainty']), ('', ''))
        self.assertEqual(data['issued_at'], run['run_at'].replace('T', ' ')[:16])
        self.assertEqual(data['details']['technician'], 'T. Tech')
        self.assertIsNone(data['show_tar_tur'])

    def test_rebuild_declined_writes_nothing(self):
        choose, overwrite, log = asking(self.dir / 'r.pdf')
        res = rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite, confirm_rebuilt=lambda m: False)
        self.assertFalse(res.ok)
        self.assertEqual((res.message, log), ('', []))
        self.assertFalse((self.dir / 'r.pdf').exists())

    def test_incomplete_history_gets_a_plain_message_and_nothing_is_invented(self):
        self.edit('DELETE FROM points WHERE rowid=(SELECT MAX(rowid) FROM points)')
        pl = rs.plan(self.rid)
        self.assertEqual(pl.kind, rs.NONE)
        self.assertIn('no saved report record', pl.message)
        self.assertIn('Only 2 of the 3 points', pl.message)
        res = rs.regenerate(self.rid, choose_path=lambda n, o: str(self.dir / 'x.pdf'), confirm_overwrite=lambda p, o: True)
        self.assertFalse(res.ok)
        self.assertFalse((self.dir / 'x.pdf').exists())

    def test_points_without_an_as_found_reading_are_not_rebuilt(self):
        self.edit("UPDATE points SET found='' WHERE rowid=(SELECT MIN(rowid) FROM points)")
        self.assertEqual(rs.plan(self.rid).kind, rs.NONE)
        self.assertIn('without guessing', rs.plan(self.rid).message)

    def test_stored_pass_fail_count_must_agree_with_the_points(self):
        self.edit('UPDATE runs SET failed=0')
        self.assertEqual(rs.plan(self.rid).kind, rs.NONE)

    def test_unknown_event(self):
        self.assertEqual(rs.plan(9999).kind, rs.NONE)
        self.assertEqual(rs.load(9999).status, rs.MISSING)


class Regenerate(Base):
    def setUp(self):
        super().setUp()
        tt = report_pdf.apply_tar_tur(rows(), True, [{'TAR': '4.0:1', 'TUR': '3.1:1'}] * 3)
        report_pdf.write_calibration_pdf(str(self.dir / 'orig.pdf'), tt, header=HEADER, details=dict(R.DETAILS, show_tar_tur=report_pdf.TarTur(True, True)))
        self.rid = labregistry.runs_for('A-7')[0]['id']

    def test_default_name_is_asset_and_original_issue_date(self):
        choose, overwrite, log = asking(self.dir / 'new.pdf')
        res = rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite, now=LATER)
        self.assertTrue(res.ok, res.message)
        self.assertEqual(log[0][1], 'A-7-01-02-2026.pdf')
        self.assertEqual(log[0][2], str(self.dir / 'orig.pdf'), 'the dialog is offered the folder of the original')
        self.assertEqual(rs.reprint_filename('A-7', '2026-01-02 03:04'), 'A-7-01-02-2026.pdf')
        self.assertEqual(rs.reprint_filename('A 7/x', '2026-01-02T03:04:05'), 'A_7_x-01-02-2026.pdf')

    def test_original_issue_date_and_details_stay_as_recorded(self):
        out = self.dir / 'new.pdf'
        later = type('LaterClock', (datetime,), {'now': classmethod(lambda cls, tz=None: LATER)})
        with mock.patch.object(report_pdf, 'datetime', later):            # the PDF writer's own clock says another day
            choose, overwrite, _ = asking(out)
            rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite, now=LATER)
        text = R.pdf_text(out)
        self.assertIn('Report date: 2026-01-02 03:04', text)
        self.assertNotIn('2026-10-22 09:30', text)
        self.assertIn('Reprinted 2026-10-22 from the saved record.', text)
        self.assertEqual(rs._restore(rs.load(self.rid).data['details'])['technician'], 'T. Tech')

    def test_note_is_only_in_the_footer_and_metadata(self):
        out = self.dir / 'new.pdf'
        choose, overwrite, _ = asking(out)
        rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite, now=LATER)
        self.assertEqual(R.differences(self.dir / 'orig.pdf', out, 'Reprinted'), [])
        from pypdf import PdfReader
        self.assertIn('Reprinted 2026-10-22', str(PdfReader(str(out)).metadata.get('/Subject')))

    def test_existing_file_is_never_replaced_without_asking(self):
        out = self.dir / 'there.pdf'
        out.write_bytes(b'precious')
        choose, overwrite, log = asking(out, over=False)
        res = rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite)
        self.assertFalse(res.ok)
        self.assertEqual(out.read_bytes(), b'precious')
        self.assertEqual(log[-1], ('overwrite', str(out), False))
        choose, overwrite, log = asking(out, over=True)
        self.assertTrue(rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite).ok)
        self.assertTrue(out.read_bytes().startswith(b'%PDF'))

    def test_overwriting_the_original_report_file_is_flagged(self):
        choose, overwrite, log = asking(self.dir / 'orig.pdf', over=False)
        before = (self.dir / 'orig.pdf').read_bytes()
        res = rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite)
        self.assertFalse(res.ok)
        self.assertEqual(log[-1], ('overwrite', str(self.dir / 'orig.pdf'), True))
        self.assertEqual((self.dir / 'orig.pdf').read_bytes(), before)

    def test_cancelled_save_dialog_writes_nothing(self):
        res = rs.regenerate(self.rid, choose_path=lambda n, o: None, confirm_overwrite=lambda p, o: True)
        self.assertEqual((res.ok, res.message), (False, ''))

    def test_failed_write_leaves_no_partial_file(self):
        out = self.dir / 'f.pdf'
        with mock.patch.object(report_pdf, 'write_calibration_pdf', side_effect=RuntimeError('disk full')):
            res = rs.regenerate(self.rid, choose_path=lambda n, o: str(out), confirm_overwrite=lambda p, o: True)
        self.assertFalse(res.ok)
        self.assertIn('disk full', res.message)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['orig.pdf'])

    def test_reprint_writes_no_history_and_no_snapshot(self):
        choose, overwrite, _ = asking(self.dir / 'r.pdf')
        rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite)
        self.assertEqual(len(labregistry.runs_for('A-7')), 1)
        self.assertEqual(self.n_snapshots(), 1)

    def test_tar_tur_toggle_state_is_restored(self):
        out = self.dir / 'r.pdf'
        choose, overwrite, _ = asking(out)
        rs.regenerate(self.rid, choose_path=choose, confirm_overwrite=overwrite)
        self.assertEqual(R.differences(self.dir / 'orig.pdf', out, 'Reprinted'), [])
        self.assertIn('TUR', R.pdf_text(out))
        self.assertIn('3.1:1', R.pdf_text(out))


class DamagedOrMissingDatabase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_nothing_raises_on_a_missing_folder(self):
        path = self.dir / 'no' / 'such' / 'folder' / 'x.sqlite3'
        self.assertFalse(rs.record_issued(1, header=HEADER, rows=rows(), db_path=path))
        self.assertEqual(rs.load(1, db_path=path).status, rs.DAMAGED)
        self.assertEqual(rs.plan(1, db_path=path).kind, rs.NONE)
        self.assertEqual(rs.availability(1, db_path=path)[0], rs.NONE)
        self.assertFalse(rs.regenerate(1, choose_path=lambda n, o: 'x', confirm_overwrite=lambda p, o: True, db_path=path).ok)
        self.assertEqual(rs.rebuild_from_history(1, db_path=path)[0], None)

    def test_nothing_raises_on_a_damaged_file(self):
        path = self.dir / 'bad.sqlite3'
        path.write_bytes(b'this is not a database' * 50)
        self.assertFalse(rs.record_issued(1, header=HEADER, rows=rows(), db_path=path))
        self.assertEqual(rs.load(1, db_path=path).status, rs.DAMAGED)
        self.assertEqual(rs.plan(1, db_path=path).kind, rs.NONE)
        self.assertIsNone(rs.run_row(1, db_path=path))
        self.assertIn('could not be read', rs.plan(1, db_path=path).message)

    def test_the_pdf_is_still_written_when_the_registry_is_damaged(self):
        if not HAVE:
            self.skipTest('reportlab is not installed')
        bad = self.dir / 'bad.sqlite3'
        bad.write_bytes(b'garbage' * 100)
        with R.registry(db=bad):
            n = issue(self.dir / 'a.pdf')
        self.assertEqual(n, 3)
        self.assertTrue((self.dir / 'a.pdf').read_bytes().startswith(b'%PDF'))

    def test_a_locked_or_readonly_database_does_not_raise(self):
        path = self.dir / 'ro.sqlite3'
        with sqlite3.connect(str(path)) as con:
            con.execute('CREATE TABLE t(x)')
        path.chmod(0o400)
        self.assertFalse(rs.record_issued(1, header=HEADER, rows=rows(), db_path=path) and False)     # may or may not succeed as root; must not raise


class Helpers(unittest.TestCase):
    def test_context_for_never_raises_and_stamps(self):
        class Weird:
            def __getattr__(self, name):
                raise RuntimeError(name)
        self.assertIsInstance(rs.context_for(Weird()), dict)
        self.assertEqual(rs.context_for(None).get('suite', {}).get('name'), 'Calibration Suite')

    def test_context_for_an_engine_style_object(self):
        class App:
            spec = {'schema': 3, 'steps': [1, 2]}
            left = {}
        stamp = rs.context_for(App())
        self.assertEqual(stamp['spec']['schema'], 3)
        self.assertEqual(len(stamp['spec']['sha256']), 64)
        self.assertFalse(stamp['as_left_present'])
        self.assertEqual(rs.context_for(App())['spec'], stamp['spec'], 'deterministic')

    def test_reprint_note_wording(self):
        self.assertEqual(rs.reprint_note(rs.SNAPSHOT, LATER), 'Reprinted 2026-10-22 from the saved record.')
        self.assertTrue(rs.reprint_note(rs.REBUILT, LATER).startswith('REBUILT 2026-10-22 from history rows, no original snapshot'))

    def test_tar_tur_json_round_trip(self):
        v = report_pdf.TarTur(True, False)
        self.assertEqual(rs._restore(rs._jsonable({'a': [v]})), {'a': [v]})
        with self.assertRaises(ValueError):
            rs._jsonable(object())


if __name__ == '__main__':
    unittest.main()
