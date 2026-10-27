"""Field technician "Assign uncertainty" (field_uncertainty.py): detection, the two ways to assign (accept a suggestion / enter a value), refusals, storage in
lab_registry.sqlite3 only, the override layer, the PDF mark and footnote, demo mode, the owner's list.  Real Truevolt 34470A engine rows from the simulated bench plus two
recorded points the lab scope does not cover (tests/field_uncertainty_harness.py).  No tkinter window; no Qt here (see test_qt_field_uncertainty).
Run:  python -m unittest tests.test_field_uncertainty
"""
import contextlib
import csv
import hashlib
import io
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import field_uncertainty_harness as H  # noqa: E402
import reprint_harness as R  # noqa: E402
import field_uncertainty as F  # noqa: E402
import labregistry  # noqa: E402
import report_pdf  # noqa: E402
import test_reprint_review as T  # noqa: E402

D = Decimal
WHO = 'A. Technician'
try:
    import reportlab  # noqa: F401
    HAVE_PDF = subprocess.run(['pdftotext', '-v'], capture_output=True).returncode in (0, 99)
except Exception:
    HAVE_PDF = False


def tables(path):
    con = sqlite3.connect(str(path))
    try:
        return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    finally:
        con.close()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def computed_index(model):
    return next(i for i, r in enumerate(model.rows) if i not in model.field_missing and str(r.spec.printed.get('Uncertainty') or '').strip() not in ('', 'N/A'))


class Base(unittest.TestCase):
    def setUp(self):
        F.clear_session()
        self.addCleanup(F.clear_session)
        self.app, self.mod = H.gap_app()
        self.addCleanup(H.drop_gap_points, self.mod)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.reg = self.stack.enter_context(H.registry())
        self.model = H.review_model(self.app)
        self.idx = sorted(self.model.field_missing)[0]
        self.info = F.point_info(self.model, self.idx)

    def sug(self):
        s = F.suggestions(self.model, self.idx)
        self.assertTrue(s, 'the gap point should have at least one suggestion')
        return s[0]

    def accept(self):
        s = self.sug()
        return F.add(self.info, s.value, source=s.source, reason='', who=WHO, confirm_below_cmc=False), s


class Detection(unittest.TestCase):
    def test_shipped_points_have_no_gap_and_gap_points_are_found(self):
        F.clear_session()
        app, mod = T.truevolt_app()
        with H.registry():
            model = H.review_model(app)
            self.assertEqual(model.field_missing, {}, 'a normal run has no point without an uncertainty')
        app, mod = H.gap_app()
        self.addCleanup(H.drop_gap_points, mod)
        with H.registry():
            model = H.review_model(app)
            self.assertEqual(len(model.field_missing), 2)
            for i, miss in model.field_missing.items():
                self.assertEqual(miss.reason, 'none')
                self.assertFalse(miss.covered)
                self.assertEqual(str(model.rows[i].spec.printed.get('Uncertainty') or '').strip(), '')
            self.assertEqual(model.field_procedure, 'truevolt_verification:34470A')

    def test_detection_does_not_change_the_review_numbers(self):
        app, mod = H.gap_app()
        self.addCleanup(H.drop_gap_points, mod)
        import report_review_model as M
        with H.registry():
            specs, default = M.specs_for(app)
            plain = M.ReviewModel(specs, default, asset='A-100', procedure='p')
            before = [(dict(r.spec.printed), r.spec.low, r.spec.high, r.status) for r in plain.rows]
            F.annotate(plain, app, False)
            after = [(dict(r.spec.printed), r.spec.low, r.spec.high, r.status) for r in plain.rows]
            self.assertEqual(before, after)

    def test_na_points_count(self):
        app, mod = H.gap_app()
        self.addCleanup(H.drop_gap_points, mod)
        with H.registry():
            model = H.review_model(app)
            i = sorted(model.field_missing)[0]
            model.rows[i].spec.printed['Uncertainty'] = 'N/A'
            self.assertEqual(F.detect(model, app)[i].reason, 'na')

    def test_typed_value_is_not_missing(self):
        app, mod = H.gap_app()
        self.addCleanup(H.drop_gap_points, mod)
        with H.registry():
            model = H.review_model(app)
            i = sorted(model.field_missing)[0]
            model.rows[i].typed = {'Uncertainty': '1 mV'}
            self.assertNotIn(i, F.detect(model, app))


class Assigning(Base):
    def test_suggestions_are_ranked_and_labelled(self):
        s = F.suggestions(self.model, self.idx)
        self.assertEqual([x.rank for x in s], sorted(x.rank for x in s))
        for x in s:
            self.assertGreater(x.value, 0)
            self.assertTrue(x.source.startswith('suggested:'))
            self.assertTrue(x.display and x.basis)
        self.assertTrue(s[0].caution, 'an extrapolated suggestion must carry a caution')

    def test_accept_a_suggestion_is_one_step_and_needs_only_a_name(self):
        aid, s = self.accept()
        a = F.lookup(self.info.procedure, self.info.section, self.info.description, self.info.nominal_text)
        self.assertEqual(a['id'], aid)
        self.assertEqual(a['source'], s.source)
        self.assertEqual(D(a['value']), s.value)
        self.assertEqual(a['who'], WHO)
        self.assertEqual(a['unit'], 'V')
        self.assertTrue(a['at'])
        self.assertIsNotNone(a['app_version'])
        self.assertEqual(a['first_asset'], 'A-100')
        self.assertIsNone(a['first_run'])
        self.assertEqual(a['active'], 1)

    def test_enter_own_value_keeps_decimal_text_and_reason(self):
        chk = F.check_manual(self.info, '12.5', D('1e-3'))        # 12.5 mV, the unit chosen in the panel
        self.assertTrue(chk.ok, chk.errors)
        self.assertEqual(chk.value, D('0.0125'))
        self.assertEqual(chk.display, '12.5 mV')
        aid = F.add(self.info, chk.value, source='manual', reason='Scope bandwidth limit at 2 MHz', who=WHO, confirm_below_cmc=chk.below_cmc)
        a = F.all_assignments()[0]
        self.assertEqual(a['value'], '0.0125')
        self.assertEqual(a['display'], '12.5 mV')
        self.assertEqual(a['source'], 'manual')
        self.assertEqual(a['reason'], 'Scope bandwidth limit at 2 MHz')
        self.assertEqual(a['id'], aid)

    def test_display_scaling_does_not_change_the_stored_value(self):
        for text, factor in (('0.0125', D(1)), ('12.5', D('1e-3')), ('12500', D('1e-6')), ('12.5 mV', D(1))):
            self.assertEqual(F.check_manual(self.info, text, factor).value, D('0.0125'), text)

    def test_unit_prefixes_and_refusals_in_parsing(self):
        for text in ('abc', '', '1 kg', '1 mA', '1e400', '0', '-3', 'nan', 'inf'):
            self.assertFalse(F.check_manual(self.info, text).ok, text)
        self.assertEqual(F.check_manual(self.info, '3 uV').value, D('3E-6'))
        self.assertEqual(F.check_manual(self.info, '3 µV').value, D('3E-6'))

    def test_validation_and_refusals(self):
        s = self.sug()
        cases = [('people', dict(reason='', who='', source=s.source)),
                 ('people', dict(reason='', who=WHO, source='manual')),
                 ('people', dict(reason='the password is hunter2 for the unit', who=WHO, source='manual')),
                 ('people', dict(reason='fine reason here', who='my password=x', source='manual')),
                 ('source', dict(reason='fine reason here', who=WHO, source='guess')),
                 ('value', dict(reason='fine reason here', who=WHO, source='manual', value=D(0))),
                 ('value', dict(reason='fine reason here', who=WHO, source='manual', value=D(-1))),
                 ('value', dict(reason='fine reason here', who=WHO, source='manual', value=D(5))),
                 ('value', dict(reason='fine reason here', who=WHO, source='manual', value=D('1e-20'))),
                 ('below_cmc', dict(reason='fine reason here', who=WHO, source='manual', value=D('0.0001')))]
        for code, kw in cases:
            kw = dict(kw)
            value = kw.pop('value', s.value)
            with self.assertRaises(F.Refused) as cm:
                F.add(self.info, value, **kw)
            self.assertEqual(cm.exception.code, code, (code, kw))
        self.assertEqual(F.all_assignments(), [], 'nothing is kept after a refusal')

    def test_below_cmc_needs_confirmation_and_is_recorded(self):
        low = D('0.0001')
        self.assertTrue(F.check_value(self.info, low).below_cmc)
        self.assertIn('Below the lab CMC', F.check_value(self.info, low).warnings[0])
        F.add(self.info, low, source='manual', reason='Own measurement shows less', who=WHO, confirm_below_cmc=True)
        self.assertEqual(F.all_assignments()[0]['below_cmc_confirmed'], 1)

    def test_a_point_with_a_computed_uncertainty_is_not_overridden_without_replace(self):
        info = F.point_info(self.model, computed_index(self.model))
        self.assertTrue(info.has_computed)
        v = D('0.5') * D(repr(float(info.nominal or 1))) / 1000
        with self.assertRaises(F.Refused) as cm:
            F.add(info, v, source='manual', reason='Because I say so', who=WHO, confirm_below_cmc=True)
        self.assertEqual(cm.exception.code, 'has_computed')
        with self.assertRaises(F.Refused):
            F.add(info, v, source='manual', reason='no', who=WHO, replace=True, confirm_below_cmc=True)       # replace needs a real reason
        F.add(info, v, source='manual', reason='Computed value is not valid for this setup', who=WHO, replace=True, confirm_below_cmc=True)
        a = F.all_assignments()[0]
        self.assertEqual((a['replaces'], a['replaced_text']), (1, info.computed_text))

    def test_group_apply_counts_and_is_safe(self):
        grp = F.kind_group(self.model, self.idx, 'manual', D('0.02'))
        self.assertEqual(grp['items'], [], 'one typed number is not spread over points with other conditions (2 MHz vs 5 MHz)')
        self.assertEqual(grp['skipped'], 1)
        grp = F.kind_group(self.model, self.idx, 'suggested', suggestion=self.sug())
        for info, value, source in grp['items']:
            self.assertNotEqual(info.key, self.info.key)
            self.assertFalse(info.has_computed)
            self.assertEqual(info.kind, self.info.kind)
            self.assertTrue(source.startswith('suggested:'))
        s = self.sug()
        items = [(self.info, s.value, s.source)] + grp['items']
        ids = F.add_many(items, reason='', who=WHO, scope='kind')
        rows = F.all_assignments()
        self.assertEqual(len(rows), len(items))
        if len(items) > 1:
            self.assertEqual(len({r['group_id'] for r in rows}), 1)
            self.assertTrue(all(r['scope'] == 'kind' for r in rows))
        self.assertEqual(ids, [r['id'] for r in rows])

    def test_group_of_a_typed_value_covers_only_identical_conditions(self):
        F.clear_session()
        H.drop_gap_points(self.mod)
        self.app, self.mod = H.gap_app(twin=True)
        self.model = H.review_model(self.app)
        self.idx = next(i for i in sorted(self.model.field_missing) if '2 MHz' in self.model.rows[i].spec.nominal_text and self.model.rows[i].spec.description.endswith('200 Hz filter'))
        self.info = F.point_info(self.model, self.idx)
        grp = F.kind_group(self.model, self.idx, 'manual', D('0.0125'))
        self.assertEqual([x.description for x, _v, _s in grp['items']], ['1 V range, 20 Hz filter'])
        self.assertEqual(grp['skipped'], 1, 'the 5 MHz point has other conditions')
        ids = F.add_many([(self.info, D('0.0125'), 'manual')] + grp['items'], reason='Same fixture for both repeats', who=WHO, scope='kind')
        self.assertEqual(len(ids), 2)
        self.assertEqual({r['scope'] for r in F.all_assignments()}, {'kind'})
        # points that already carry a value are never in a group
        self.model = H.review_model(self.app)
        self.assertEqual(len([r for r in self.model.rows if r.assigned is not None]), 2)

    def test_group_is_all_or_none(self):
        s = self.sug()
        other = F.point_info(self.model, sorted(self.model.field_missing)[1])
        with self.assertRaises(F.Refused):
            F.add_many([(self.info, s.value, s.source), (other, D('1000'), s.source)], reason='', who=WHO)
        self.assertEqual(F.all_assignments(), [])

    def test_withdraw_keeps_the_record(self):
        aid, _ = self.accept()
        with self.assertRaises(F.Refused):
            F.withdraw(aid, WHO, '')
        self.assertTrue(F.withdraw(aid, WHO, 'Entered on the wrong unit'))
        self.assertFalse(F.withdraw(aid, WHO, 'again please'))
        self.assertIsNone(F.lookup(self.info.procedure, self.info.section, self.info.description, self.info.nominal_text))
        rec = F.all_assignments(include_withdrawn=True)
        self.assertEqual(len(rec), 1)
        self.assertEqual(F.status_of(rec[0]), 'withdrawn')
        self.assertEqual(F.all_assignments(include_withdrawn=False), [])
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        F.export_csv(tmp / 'w.csv')
        rec = list(csv.DictReader(io.StringIO((tmp / 'w.csv').read_text(encoding='utf-8-sig'))))
        self.assertEqual((rec[0]['status'], rec[0]['withdrawn_by'], rec[0]['withdrawn_reason']), ('withdrawn', WHO, 'Entered on the wrong unit'))

    def test_read_back_mismatch_is_an_error_and_not_retried(self):
        s = self.sug()
        calls = []
        with mock.patch.object(F, '_read_back', lambda con, aid, expected: calls.append(aid) or False):
            with self.assertRaises(F.StorageError):
                F.add(self.info, s.value, source=s.source, reason='', who=WHO)
        self.assertEqual(len(calls), 1, 'one write, one read back, no retry')
        self.assertEqual(F.all_assignments(), [], 'the failed write was rolled back')

    def test_insert_error_is_not_retried(self):
        s = self.sug()
        n = []

        class Con:
            def __init__(self, real):
                self.real = real

            def execute(self, sql, *a):
                if sql.lstrip().startswith('INSERT'):
                    n.append(1)
                    raise sqlite3.OperationalError('disk I/O error')
                return self.real.execute(sql, *a)

            def __getattr__(self, k):
                return getattr(self.real, k)

        real_db = F._db

        @contextlib.contextmanager
        def wrapped():
            with real_db() as con:
                yield Con(con)
        with mock.patch.object(F, '_db', wrapped):
            with self.assertRaises(F.StorageError):
                F.add(self.info, s.value, source=s.source, reason='', who=WHO)
        self.assertEqual(len(n), 1)


class Storage(Base):
    def test_table_is_created_on_first_write_only_and_is_idempotent(self):
        self.assertFalse(self.reg.exists(), 'detecting and annotating never create the registry')
        F.lookup_all(self.info.procedure)
        F.all_assignments()
        self.assertFalse(self.reg.exists(), 'reading never creates it')
        F.suggestions(self.model, self.idx)                  # may open the registry through uncertainty_fixes (existing tables), never ours
        if self.reg.exists():
            self.assertNotIn('field_uncertainty', tables(self.reg))
        self.accept()
        self.assertIn('field_uncertainty', tables(self.reg))
        before = tables(self.reg)
        for _ in range(3):
            with F._db():
                pass
        self.assertEqual(tables(self.reg), before)
        self.assertEqual(len(F.all_assignments()), 1, 'repeated schema runs keep the data')

    def test_existing_registry_tables_are_untouched(self):
        con = sqlite3.connect(str(self.reg))
        con.execute('CREATE TABLE asset_history(id INTEGER PRIMARY KEY, note TEXT)')
        con.execute("INSERT INTO asset_history(note) VALUES ('keep me')")
        con.commit()
        con.close()
        con = sqlite3.connect(str(self.reg))
        base = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
        con.close()
        self.accept()
        con = sqlite3.connect(str(self.reg))
        after = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
        kept = con.execute('SELECT note FROM asset_history').fetchall()
        con.close()
        for name, sql in base.items():
            self.assertEqual(after[name], sql, name)
        self.assertEqual(set(after) - set(base) - {'sqlite_sequence', 'uncertainty_fixes', 'uncertainty_fixes_key', 'uncertainty_flags'}, {'field_uncertainty'})
        self.assertEqual(kept, [('keep me',)])

    def test_calibration_procedures_sqlite3_is_never_opened_or_changed(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        proc = tmp / 'calibration_procedures.sqlite3'
        con = sqlite3.connect(str(proc))
        con.execute('CREATE TABLE procedures(id INTEGER PRIMARY KEY, name TEXT)')
        con.execute("INSERT INTO procedures(name) VALUES ('x')")
        con.commit()
        con.close()
        before, stamp = digest(proc), proc.stat().st_mtime_ns
        opened = []
        real = sqlite3.connect

        def spy(database, *a, **k):
            opened.append(str(database))
            return real(database, *a, **k)
        with mock.patch.object(sqlite3, 'connect', spy):
            aid, _ = self.accept()
            F.withdraw(aid, WHO, 'testing the withdraw')
            F.all_assignments()
            F.export_csv(tmp / 'out.csv')
        self.assertTrue(opened)
        self.assertFalse([p for p in opened if 'calibration_procedures' in p], opened)
        self.assertEqual((digest(proc), proc.stat().st_mtime_ns), (before, stamp))
        for name in ('field_uncertainty.py', 'qtui/screens/field_uncertainty_panel.py', 'field_uncertainty_view_qt.py'):
            src = (HERE.parent / name).read_text(encoding='utf-8')
            self.assertNotIn('appdata', src, name)

    def test_mark_used_sets_the_run_once(self):
        aid, _ = self.accept()
        self.assertEqual(F.mark_used([aid], 'A-100', 7), 1)
        F.mark_used([aid], 'OTHER', 8)
        a = F.all_assignments()[0]
        self.assertEqual((a['first_asset'], a['first_run']), ('A-100', 7))

    def test_newest_active_assignment_wins_and_is_per_procedure(self):
        s = self.sug()
        F.add(self.info, s.value, source=s.source, reason='', who=WHO)
        F.add(self.info, s.value * 2, source='manual', reason='Second thoughts on it', who=WHO, confirm_below_cmc=True)
        self.assertEqual(D(F.lookup(self.info.procedure, self.info.section, self.info.description, self.info.nominal_text)['value']), s.value * 2)
        self.assertEqual(F.lookup_all('another:procedure'), {})

    def test_no_password_in_the_database_or_the_logs(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        old = root.level
        root.setLevel(logging.DEBUG)
        self.addCleanup(lambda: (root.removeHandler(handler), root.setLevel(old)))
        s = self.sug()
        for reason, who in (('password is hunter2', WHO), ('PIN: 1234 for the case', WHO), ('Credential in my notes', WHO), ('fine reason here', 'passwd=abc')):
            with self.assertRaises(F.Refused) as cm:
                F.add(self.info, s.value, source='manual', reason=reason, who=who, confirm_below_cmc=True)
            self.assertNotIn('hunter2', str(cm.exception))
            self.assertNotIn('1234', str(cm.exception))
        self.assertEqual(F.all_assignments(), [])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            self.accept()
        self.assertNotIn('hunter2', stream.getvalue() + out.getvalue())
        raw = self.reg.read_bytes()
        for needle in (b'hunter2', b'passwd=abc', b'PIN: 1234'):
            self.assertNotIn(needle, raw)


class CsvList(Base):
    def test_export_has_every_field_and_guards_formulas(self):
        s = self.sug()
        F.add(self.info, s.value, source=s.source, reason='', who='=cmd|calc')
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        out = tmp / 'list.csv'
        self.assertEqual(F.export_csv(out), 1)
        raw = out.read_bytes()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertEqual(tuple(rows[0]), F.CSV_COLUMNS)
        rec = dict(zip(rows[0], rows[1]))
        for k in ('procedure', 'point', 'printed', 'source', 'assigned_by', 'assigned_at', 'status'):
            self.assertTrue(rec[k], k)
        self.assertEqual(rec['assigned_by'], "'=cmd|calc")
        self.assertEqual(rec['status'], 'active')
        self.assertEqual(rec['procedure'], 'truevolt_verification:34470A')

    def test_empty_list_is_just_the_header(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        out = tmp / 'e.csv'
        self.assertEqual(F.export_csv(out), 0)
        self.assertEqual(len(out.read_text(encoding='utf-8-sig').strip().split('\n')), 1)


class OverrideLayer(Base):
    def rows(self):
        out = []
        for r in self.model.rows:
            sp = r.spec
            out.append({'Section': sp.section, 'Description': sp.description, 'Nominal': sp.nominal_text, 'Result': 'PASS', 'Uncertainty': str(sp.printed.get('Uncertainty') or ''),
                        'TUR': '', 'Tolerance -': str(sp.low), 'Tolerance +': str(sp.high), 'UOM': sp.unit})
        return out

    def details(self):
        return {'procedure': 'x', 'field_procedure': self.info.procedure}

    def test_nothing_stored_returns_the_same_objects(self):
        rows, details = self.rows(), self.details()
        r2, d2, notes = F.apply_to_rows(rows, details, None)
        self.assertIs(r2, rows)
        self.assertIs(d2, details)
        self.assertEqual(notes, [])

    def test_only_empty_cells_are_filled_and_nothing_else_moves(self):
        s = self.sug()
        F.add(self.info, s.value, source=s.source, reason='', who=WHO)
        rows, details = self.rows(), self.details()
        r2, d2, notes = F.apply_to_rows(rows, details, None)
        self.assertEqual(len(notes), 1)
        hit = 0
        for a, b in zip(rows, r2):
            if (a['Description'], a['Nominal']) == (self.info.description, self.info.nominal_text):
                hit += 1
                self.assertEqual(b['Uncertainty'], F.marked(F.format_decimal(s.value, 'V'), 1))
                self.assertEqual({k: v for k, v in a.items() if k not in ('Uncertainty', 'TUR')}, {k: v for k, v in b.items() if k not in ('Uncertainty', 'TUR')})
            else:
                self.assertEqual(a, b, 'every other row is unchanged')
        self.assertEqual(hit, 1)
        self.assertNotIn('field_assignments', details, "the caller's details are not mutated")
        self.assertEqual(d2['field_assignments'][0]['who'], WHO)

    def test_computed_uncertainty_is_never_replaced_without_the_explicit_choice(self):
        info = F.point_info(self.model, computed_index(self.model))
        with F._db() as con:        # planted behind the API's back
            vals = F._values(info, D('0.123'), '123 mV', 'manual', 'planted for the test', WHO, False, 'point', '', False, 'A-100', '')
            con.execute(f'INSERT INTO field_uncertainty({", ".join(F._INSERT_COLS)}) VALUES ({", ".join("?" * len(F._INSERT_COLS))})', tuple(vals[c] for c in F._INSERT_COLS))
        rows = self.rows()
        r2, d2, notes = F.apply_to_rows(rows, self.details(), None)
        self.assertEqual(notes, [])
        self.assertEqual(r2, rows)

    def test_replace_changes_only_the_uncertainty_and_says_what_it_replaced(self):
        info = F.point_info(self.model, computed_index(self.model))
        F.add(info, D('0.0007'), source='manual', reason='Computed value is not valid here', who=WHO, replace=True, confirm_below_cmc=True)
        rows = self.rows()
        r2, d2, notes = F.apply_to_rows(rows, self.details(), None)
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0]['replaces'])
        self.assertEqual(notes[0]['replaced'], info.computed_text)
        changed = [(a, b) for a, b in zip(rows, r2) if a != b]
        self.assertEqual(len(changed), 1)
        a, b = changed[0]
        self.assertEqual({k: v for k, v in a.items() if k not in ('Uncertainty', 'TUR')}, {k: v for k, v in b.items() if k not in ('Uncertainty', 'TUR')})
        self.assertIn('assigned in the field', b['Uncertainty'])
        self.assertTrue(any('replaces the computed value' in t for _k, t in F.footnote_lines(notes)))

    def test_reprint_never_picks_up_a_later_assignment(self):
        self.accept()
        rows, details = self.rows(), self.details()
        r2, d2, notes = F.apply_to_rows(rows, details, None, reprint=True)
        self.assertIs(r2, rows)
        self.assertEqual(notes, [])
        # a snapshot written WITH the notes reprints with them and looks nothing up
        r3, d3, _n = F.apply_to_rows(rows, details, None)
        F.withdraw(F.all_assignments()[0]['id'], WHO, 'withdrawn later on')
        r4, d4, n4 = F.apply_to_rows(r3, d3, None, reprint=True)
        self.assertEqual(len(n4), 1, 'withdrawing later does not change an issued report')
        self.assertEqual(r4, r3)

    def test_footnote_wording(self):
        self.accept()
        _r, _d, notes = F.apply_to_rows(self.rows(), self.details(), None)
        lines = F.footnote_lines(notes)
        self.assertEqual([k for k, _t in lines], ['head', 'intro', 'note'])
        self.assertIn(WHO, lines[2][1])
        self.assertIn('suggestion:', lines[2][1])
        self.assertEqual(F.footnote_lines([]), [])

    def test_review_numbers_are_the_same_with_and_without_an_assignment(self):
        before = [(r.spec.printed.get('Uncertainty'), r.spec.low, r.spec.high, r.status) for r in self.model.rows]
        self.accept()
        model2 = H.review_model(self.app)
        after = [(r.spec.printed.get('Uncertainty'), r.spec.low, r.spec.high) for r in model2.rows]
        self.assertEqual([b[:3] for b in before], after)
        self.assertIsNotNone(model2.rows[self.idx].assigned)


@unittest.skipUnless(HAVE_PDF, 'reportlab and pdftotext are needed')
class PdfReport(Base):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def export(self, name, app=None, mod=None, **details):
        out = self.tmp / name
        T.export(app or self.app, mod or self.mod, out, dict(R.DETAILS, **details))
        return out

    def test_marked_value_and_footnote_in_the_pdf(self):
        s = self.sug()
        aid = F.add(self.info, s.value, source=s.source, reason='', who=WHO)
        flat = ' '.join(R.pdf_text(self.export('a.pdf', field_procedure=self.info.procedure)).split())
        self.assertIn('(assigned in the field, note 1)', flat)
        self.assertIn('Uncertainties assigned in the field', flat)
        self.assertIn('NOT the result of the laboratory uncertainty budget', flat)
        self.assertIn(WHO, flat)
        self.assertIn('suggestion: nearest lab CMC line', flat)
        run = R.last_run_id('A-100')
        self.assertIsNotNone(run)
        a = F.all_assignments()[0]
        self.assertEqual((a['id'], a['first_asset'], a['first_run']), (aid, 'A-100', run))

    def test_without_an_assignment_the_pdf_is_the_same_as_without_the_layer(self):
        a = self.export('a.pdf', field_procedure=self.info.procedure)
        with mock.patch.object(report_pdf, 'apply_field_assignments', lambda rows, details, header=None, demo=False, reprint=False: (rows, details, [])):
            b = self.export('b.pdf', field_procedure=self.info.procedure)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertNotIn('assigned in the field', R.pdf_text(a))

    def test_pass_fail_in_the_pdf_does_not_change_when_an_assignment_exists(self):
        a = self.export('a.pdf', field_procedure=self.info.procedure)
        self.accept()
        b = self.export('b.pdf', field_procedure=self.info.procedure)
        ta, tb = R.pdf_text(a), R.pdf_text(b)
        words = lambda t: [w for w in t.split() if w in ('PASS', 'FAIL')]
        self.assertEqual(words(ta), words(tb))
        self.assertNotEqual(ta, tb)

    def test_regenerate_prints_what_was_issued(self):
        before = self.export('before.pdf', field_procedure=self.info.procedure)
        rid_a = R.last_run_id('A-100')
        self.accept()                                            # assigned AFTER the first report was issued
        out = self.tmp / 're_a.pdf'
        T.regenerate(rid_a, out)
        self.assertNotIn('assigned in the field', R.pdf_text(out), 'an old report never picks up a later assignment')
        self.export('after.pdf', field_procedure=self.info.procedure)
        rid_b = R.last_run_id('A-100')
        F.withdraw(F.all_assignments()[0]['id'], WHO, 'withdrawn after issue')
        out2 = self.tmp / 're_b.pdf'
        T.regenerate(rid_b, out2)
        flat = ' '.join(R.pdf_text(out2).split())
        self.assertIn('(assigned in the field, note 1)', flat)
        self.assertIn(WHO, flat)

    def test_demo_report_does_not_persist_and_stays_stamped(self):
        app, mod = H.gap_app(demo=True)
        self.addCleanup(H.drop_gap_points, mod)
        model = H.review_model(app, demo=True)
        idx = sorted(model.field_missing)[0]
        info = F.point_info(model, idx)
        s = F.suggestions(model, idx)[0]
        F.add(info, s.value, source=s.source, reason='', who=WHO, demo=True)
        self.assertTrue(not self.reg.exists() or 'field_uncertainty' not in tables(self.reg), 'a demonstration assignment never reaches the registry')
        self.assertEqual(len(F.all_assignments(demo=True)), 1)
        self.assertEqual(F.all_assignments(demo=False), [])
        text = R.pdf_text(self.export('demo.pdf', app, mod, field_procedure=info.procedure))
        self.assertIn('DEMO DATA - NOT CALIBRATION EVIDENCE', text)
        self.assertIn('assigned in the field', ' '.join(text.split()))
        self.assertTrue(not self.reg.exists() or 'field_uncertainty' not in tables(self.reg))

    def test_demo_registry_file_is_never_written(self):
        demo_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, demo_dir, True)
        demo_db = demo_dir / labregistry.DEMO_DB_NAME
        s = self.sug()
        with mock.patch.object(labregistry, 'DB', demo_db):
            with self.assertRaises(F.StorageError) as cm:
                F.add(self.info, s.value, source=s.source, reason='', who=WHO)
            self.assertIsInstance(cm.exception.__cause__, labregistry.DemoRegistryError)
        self.assertFalse(demo_db.exists())


@unittest.skipUnless(HAVE_PDF, 'reportlab and pdftotext are needed')
class EveryEngineUnchanged(unittest.TestCase):
    """With no assignment stored, the report of every multimeter engine (tests/dmm_export_harness.py: the engines' own export_pdf on their demo readings, pinned clock) carries no
    trace of the feature, and nothing was added to the registry.  Set FIELD_BASELINE_ROOT to a checkout of the commit before this feature to compare the PDFs byte for byte
    (done once by hand for the delivery: 30 PDFs from the DMM harness in three TAR / TUR modes, the Truevolt, TDS2000C and demo exports of reprint_harness; all identical)."""

    @staticmethod
    def dump(root, out):
        """The harness in its own process (it re-imports the engines from `root`, which must not disturb this process)."""
        r = subprocess.run([sys.executable, str(HERE / 'dmm_export_harness.py'), str(root), str(out), 'none'], capture_output=True, text=True, cwd=str(root))
        if r.returncode:
            raise AssertionError(r.stderr[-800:])
        return {p.stem: p for p in Path(out).glob('*.pdf')}

    def test_reports_have_no_trace_without_an_assignment(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        new = self.dump(HERE.parent, tmp / 'new')
        self.assertGreaterEqual(len(new), 9)
        for name, pdf in new.items():
            text = R.pdf_text(pdf)
            self.assertNotIn('assigned in the field', text, name)
            self.assertNotIn('Uncertainties assigned', text, name)
        for db in tmp.rglob('lab_registry.sqlite3'):
            self.assertNotIn('field_uncertainty', tables(db), 'a report with nothing assigned never creates the table')
        base = os.environ.get('FIELD_BASELINE_ROOT')
        if base:
            old = self.dump(Path(base), tmp / 'old')
            self.assertEqual(sorted(old), sorted(new))
            for name in new:
                self.assertEqual(new[name].read_bytes(), old[name].read_bytes(), name)


if __name__ == '__main__':
    unittest.main()
