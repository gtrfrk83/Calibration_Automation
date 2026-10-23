"""Standards spec editor, model level (no Tk): typed values, differences, validation (per-row issue list), the documented save / restore pipeline, the
append-only log, backups, rebuild of the standard in lab_registry.sqlite3, and what the edit does NOT touch.

    python -m unittest tests.test_spec_editor
"""
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import spec_edit_io as eio  # noqa: E402
import spec_edit_log as elog  # noqa: E402
import spec_editor as se  # noqa: E402
import specmanager as sm  # noqa: E402

SHEETS = sorted((ROOT / 'specs' / 'standards').glob('*_standard.json'))
COIL = 'a2la_5500a_coil_standard.json'


class Sandbox(unittest.TestCase):
    """A throw-away copy of the sheets, a throw-away lab_registry database and backup folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sd = self.tmp / 'standards'
        self.sd.mkdir()
        for f in SHEETS:
            shutil.copy(f, self.sd / f.name)
        self.db = self.tmp / 'lab_registry.sqlite3'
        self.bk = self.tmp / 'Backups' / 'spec_editor'
        sm.seed(self.sd, self.db)

    def doc(self, name=COIL):
        return se.SpecDoc.load(self.sd / name)

    def save(self, doc, **kw):
        args = dict(edited_by='Mike', reason='test edit', source='unit test', db_path=self.db, backup_dir=self.bk)
        args.update(kw)
        return eio.save_edit(doc, **args)

    def edited_doc(self):
        d = self.doc()
        d.edit_cell(d.lines()[0].iid, 'res', '0.01 A')
        return d


class Typed(unittest.TestCase):
    def test_quantity_units(self):
        self.assertEqual(se.parse_quantity('0.1 mA', 'A'), Decimal('0.0001'))
        self.assertEqual(se.parse_quantity('90', 'A'), Decimal('90'))
        self.assertEqual(se.parse_quantity('2.5 kohm', 'ohm'), Decimal('2500'))
        self.assertEqual(se.parse_quantity('3 µV', 'V'), Decimal('0.000003'))
        self.assertEqual(se.parse_quantity('10 Ω', 'ohm'), Decimal('10'))
        self.assertEqual(se.parse_quantity('25 degC', 'degC'), Decimal('25'))
        with self.assertRaises(se.EditError):
            se.parse_quantity('5 V', 'A')                       # a wrong unit is refused, not guessed
        with self.assertRaises(se.EditError):
            se.parse_quantity('5 mA', '')                       # a row with no unit takes plain numbers only
        with self.assertRaises(se.EditError):
            se.parse_quantity('abc', 'A')
        with self.assertRaises(se.EditError):
            se.parse_quantity('nan', 'A')
        with self.assertRaises(se.EditError):
            se.parse_quantity('1 mdBm', 'dBm')                 # no prefix on a unit that takes none

    def test_ratio(self):
        self.assertEqual(se.parse_ratio('0.8 %'), Decimal('0.008'))
        self.assertEqual(se.parse_ratio('90 ppm'), Decimal('0.00009'))
        self.assertEqual(se.parse_ratio('90 uA/A'), Decimal('0.00009'))
        self.assertEqual(se.parse_ratio('0.0009'), Decimal('0.0009'))
        with self.assertRaises(se.EditError):
            se.parse_ratio('90 V')

    def test_decimal_not_float(self):
        self.assertEqual(se.to_float(se.parse_quantity('0.3 mA', 'A')), 0.0003)         # 3 * 0.1 style float noise never enters
        with self.assertRaises(se.EditError):
            se.to_float(Decimal('1.234567890123456789'))                                 # more digits than the file keeps

    def test_span(self):
        self.assertEqual(se.parse_span('2 to 20 A', 'A'), (Decimal(2), Decimal(20)))
        self.assertEqual(se.parse_span('2 to 20 mA', 'A'), (Decimal('0.002'), Decimal('0.02')))      # the unit of the right side applies to a bare left number
        self.assertEqual(se.parse_span('10 Hz to 1 kHz', 'Hz'), (Decimal(10), Decimal(1000)))
        self.assertEqual(se.parse_span('', 'A'), (None, None))
        with self.assertRaises(se.EditError):
            se.parse_span('20 to 2 A', 'A')
        with self.assertRaises(se.EditError):
            se.parse_span('5 A', 'A')

    def test_display_text_types_back_to_the_stored_number(self):
        """What a cell shows (SI scaled, exact) parses back to exactly the stored number, for every number in every shipped sheet."""
        n = 0
        for f in SHEETS:
            d = se.SpecDoc.load(f)
            for _, r in d.ranges():
                u = r.get('unit') or ''
                for key in ('amp_lo', 'amp_hi', 'resolution', 'range_max'):
                    v = r.get(key)
                    if isinstance(v, (int, float)):
                        text = se.fmt_quantity(v, u)
                        if u:
                            self.assertEqual(se.parse_quantity(text, u), Decimal(repr(v)), (f.name, key, text, v))
                            n += 1
                for s in r.get('specs') or []:
                    for key in ('rel', 'fs_rel'):
                        v = s[key]
                        self.assertEqual(se.parse_ratio(se.fmt_ratio(v)), Decimal(repr(v)), (f.name, key, v))
                        n += 1
                    su = s.get('unit') or u
                    for key in ('abs', 'fs_value'):
                        v = s[key]
                        if su:
                            self.assertEqual(se.parse_quantity(se.fmt_quantity(v, su), su), Decimal(repr(v)), (f.name, key, v, su))
                            n += 1
        self.assertGreater(n, 5000)


class Shipped(unittest.TestCase):
    def test_every_sheet_round_trips_byte_for_byte_and_validates(self):
        for f in SHEETS:
            d = se.SpecDoc.load(f)
            self.assertTrue(d.style.exact, f.name)
            self.assertEqual(d.to_bytes(), d.raw, f.name)                          # an untouched document writes the identical file
            self.assertEqual(d.diff(), [], f.name)
            rep = se.validate(d)
            self.assertEqual([i.message for i in rep.errors], [], f.name)          # nothing is red on a shipped sheet
            self.assertEqual([i.message for i in rep.warnings], [], f.name)        # and no warning appears until something is edited

    def test_no_procedure_fingerprint_lists_a_standards_sheet(self):
        """So saving a sheet cannot flip any procedure to 'Changed since verification', and the new modules are in no sidecar file list."""
        for f in SHEETS:
            self.assertEqual(se.procedures_listing(f.name), [], f.name)
        for sidecar in (ROOT / 'Procedures').glob('*.procedure.json'):
            text = sidecar.read_text(encoding='utf-8')
            for name in ('spec_editor', 'spec_edit_io', 'spec_edit_log', 'spec_editor_ui'):
                self.assertNotIn(name, text, sidecar.name)

    def test_builders_that_would_overwrite_each_sheet(self):
        for f in SHEETS:
            b = se.builders_for(f.name)
            self.assertTrue(b, f.name)                                             # every shipped sheet has a builder, and every builder overwrites
        self.assertEqual([n for n, _ in se.builders_for(COIL)], ['build_coil_standard.py'])
        self.assertEqual([n for n, _ in se.builders_for('keysight_3458a_standard.json')], ['build_3458a_standard.py'])
        for script in (ROOT / 'specs').glob('build_*_standard*.py'):
            self.assertIn('out.write_text(', script.read_text(encoding='utf-8'), script.name)     # unconditional overwrite


class Editing(Sandbox):
    def test_cell_edits_and_changes(self):
        d = self.doc()
        ln = d.lines()[0]
        self.assertEqual(d.edit_cell(ln.iid, 'res', '0.01 A'), ['resolution', 'res_src'])
        r = ln.rng
        self.assertEqual((r['resolution'], r['res_src']), (0.01, 'edited'))
        cs = d.diff()
        self.assertEqual([(c.label, c.old_text, c.new_text) for c in cs], [('Resolution', '(blank)', '10.0 mA'), ('Resolution source', '(blank)', 'edited')])
        self.assertEqual(d.changed_cells(), {(ln.iid, 'res')})
        d.edit_cell(ln.iid, 'rel', '100 ppm')
        d.edit_cell(ln.iid, 'abs', '0.2 mA')
        spec = ln.spec
        self.assertEqual((spec['rel'], spec['abs']), (0.0001, 0.0002))
        self.assertEqual(d.edit_cell(ln.iid, 'rel', '100 ppm'), [])                # same value: nothing changes
        d.edit_cell(ln.iid, 'span', '1 to 30 A')
        self.assertEqual((r['amp_lo'], r['amp_hi']), (1.0, 30.0))
        d.edit_cell(ln.iid, 'page', '12')
        self.assertEqual(r['page'], 12)

    def test_bad_entries_change_nothing(self):
        d = self.doc()
        ln = d.lines()[0]
        for col, text in (('res', '5 V'), ('res', '-1 A'), ('rel', 'abc'), ('abs', '-1 mA'), ('span', '30 to 1 A'), ('page', 'x'), ('label', ''), ('period', ''), ('notes', 'a, b')):
            with self.assertRaises(se.EditError, msg=(col, text)):
                d.edit_cell(ln.iid, col, text)
        self.assertEqual(d.diff(), [])
        self.assertFalse(d.dirty)

    def test_range_level_column_needs_the_first_line(self):
        d = self.doc('fluke_5522a_standard.json')
        lines = [x for x in d.lines() if not x.first]
        self.assertTrue(lines)
        with self.assertRaises(se.EditError):
            d.edit_cell(lines[0].iid, 'label', 'x')
        d.edit_cell(lines[0].iid, 'rel', '1 ppm')                                  # a period column may be edited on any line

    def test_function_rename_is_one_change_for_every_row_of_it(self):
        d = self.doc()
        ln = d.lines()[0]
        d.edit_cell(ln.iid, 'function', 'Current, DC [renamed]')
        self.assertEqual([(c.node, c.key, c.new_text) for c in d.diff()], [('function', 'name', 'Current, DC [renamed]')])

    def test_revert_one_change_and_all(self):
        d = self.doc()
        ln = d.lines()[0]
        d.edit_cell(ln.iid, 'res', '0.01 A')
        d.edit_cell(ln.iid, 'abs', '0.2 mA')
        for c in [c for c in d.diff() if c.key in ('resolution', 'res_src')]:
            d.revert(c)
        self.assertEqual([c.key for c in d.diff()], ['abs'])
        d.discard_all()
        self.assertEqual(d.diff(), [])
        self.assertEqual(d.to_bytes(), d.raw)

    def test_add_and_delete_rows_are_documented_changes(self):
        d = self.doc()
        first = d.ranges()[0][1]
        new = d.add_range_after(first)
        self.assertEqual(len(d.ranges()), 6)
        self.assertEqual([(c.op, c.node) for c in d.diff()], [('add', 'range')])
        self.assertIn(d.uid(new), d.new_range_uids())
        d.delete_range(d.ranges()[3][1])
        ops = sorted((c.op, c.node) for c in d.diff())
        self.assertEqual(ops, [('add', 'range'), ('remove', 'range')])
        for c in list(d.diff()):
            d.revert(c)
        self.assertEqual(d.diff(), [])
        self.assertEqual(d.to_bytes(), d.raw)                                       # revert of an add and of a remove restores the exact file

    def test_removed_row_returns_where_it_was(self):
        d = self.doc()
        victim = d.ranges()[2][1]
        label = victim['label']
        d.delete_range(victim)
        d.revert(d.diff()[0])
        self.assertEqual([r['label'] for _, r in d.ranges()][2], label)
        self.assertEqual(d.to_bytes(), d.raw)

    def test_period_lines(self):
        d = self.doc('fluke_5522a_standard.json')
        rng = next(r for _, r in d.ranges() if len(r['specs']) == 2)
        s = d.add_spec_line(rng)
        rep = se.validate(d)
        self.assertTrue(any(i.code == 'period' for i in rep.errors))               # an empty period blocks saving
        d.edit_field(s, 'period', '2 yr')
        self.assertFalse(any(i.code == 'period' for i in se.validate(d).errors))
        with self.assertRaises(se.EditError):
            d.delete_spec_line(next(r for _, r in d.ranges() if len(r['specs']) == 1), None)

    def test_notes_and_info(self):
        d = self.doc()
        k = d.add_note('A new note.')
        self.assertEqual(k, '12' if '11' in d.original['notes'] else str(max(int(x) for x in d.original['notes']) + 1))
        d.edit_note('1', 'Edited text')
        d.delete_note('11')
        self.assertEqual(sorted((c.op, c.where) for c in d.changes_of('notes')), [('add', f'Note {k}'), ('remove', 'Note 11'), ('set', 'Note 1')])
        d.edit_info('revision', '10/2026')
        d.edit_info('confidence_pct', '99')
        self.assertEqual(d.current['standard']['confidence_pct'], 99.0)
        with self.assertRaises(se.EditError):
            d.edit_info('model', 'X')                                               # the model identifies the sheet in the database
        with self.assertRaises(se.EditError):
            d.edit_info('confidence_pct', '120')
        d.edit_info('confidence_pct', '')
        self.assertIsNone(d.current['standard']['confidence_pct'])

    def test_limits_and_issue_lists(self):
        d = self.doc()
        item = d.add_list_item('limits')
        self.assertEqual(len(d.list_nodes('limits')), 4)
        rep = se.validate(d)
        self.assertTrue(any(i.area == 'limits' and i.level == 'error' for i in rep.issues))      # an empty limit line is red
        d.edit_field(item, 'function', 'f')
        d.edit_field(item, 'limit', 'l')
        self.assertFalse([i for i in se.validate(d).errors if i.area == 'limits'])
        p = d.add_list_item('issues')
        d.edit_field(p, 'what', 'something')
        self.assertFalse([i for i in se.validate(d).errors if i.area == 'issues'])
        with self.assertRaises(se.EditError):
            d.edit_field(p, 'level', 'fatal')

    def test_row_details_fields(self):
        d = self.doc()
        r = d.ranges()[0][1]
        d.edit_field(r, 'variant', 'Other variant')
        d.edit_field(r, 'qualifiers', '[{"tag": "x", "lo": 1, "hi": 2, "unit": "A"}]')
        with self.assertRaises(se.EditError):
            d.edit_field(r, 'qualifiers', '{not json')
        p = r['params'][0]
        d.edit_field(p, 'notes', '5, 7, 9')
        self.assertEqual(p['notes'], [5, 7, 9])
        self.assertEqual({c.key for c in d.diff()}, {'variant', 'qualifiers', 'notes'})


class Validation(Sandbox):
    def test_missing_note_is_a_red_row_with_its_issue_text(self):
        """The owner's rule: a row with an error is red (an issue list per row), live as the edit changes."""
        d = self.doc()
        ln = d.lines()[2]
        ru = d.uid(ln.rng)
        self.assertEqual(se.validate(d).row_issues(ru), [])
        d.edit_cell(ln.iid, 'notes', '2, 99')
        rep = se.validate(d)
        issues = rep.row_issues(ru)
        self.assertEqual([(i.level, i.code) for i in issues], [('error', 'note-missing')])
        self.assertEqual(issues[0].message, 'Row 3: note 99 does not exist.')
        self.assertEqual(rep.worst('rows', ru), 'error')
        self.assertIn('note 99 does not exist', rep.text_for('rows', ru))
        self.assertFalse(rep.can_save)
        self.assertEqual({d.uid(x.rng) for x in d.lines() if rep.worst('rows', d.uid(x.rng)) == 'error'}, {ru})          # only that row is red
        self.assertEqual(rep.checks[3], ('error', '1 note reference to notes that do not exist'))
        d.edit_cell(ln.iid, 'notes', '2, 4')
        rep = se.validate(d)
        self.assertEqual(rep.row_issues(ru), [])
        self.assertEqual(rep.worst('rows', ru), '')
        self.assertTrue(rep.can_save)

    def test_deleting_a_note_makes_every_row_that_uses_it_red(self):
        d = self.doc()
        users = [d.uid(r) for _, r in d.ranges() if 5 in d.range_notes(r)]
        self.assertTrue(users)
        d.delete_note('5')
        rep = se.validate(d)
        self.assertEqual({i.target for i in rep.errors if i.code == 'note-missing'}, set(users))

    def test_every_error_class(self):
        d = self.doc()
        r = d.ranges()[0][1]
        r['amp_lo'] = float('nan')                                              # a hand-damaged number
        r['specs'][0]['rel'] = 'x'
        d.current['standard']['confidence_pct'] = 0
        d.current['notes']['3'] = ''
        d.current['functions'][0]['direction'] = 'sideways'
        d._touch()
        rep = se.validate(d)
        codes = {i.code for i in rep.errors}
        self.assertTrue({'number', 'confidence', 'note-empty', 'schema'} <= codes, codes)
        self.assertFalse(rep.can_save)
        self.assertEqual(rep.checks[0][0], 'error')
        self.assertEqual(rep.checks[1][0], 'error')

    def test_warnings_do_not_block(self):
        d = self.doc()
        d.edit_cell(d.lines()[0].iid, 'abs', '0.2 mA')
        rep = se.validate(d)
        codes = {i.code for i in rep.warnings}
        self.assertIn('raw', codes)                                             # numbers edited, printed text not
        self.assertIn('budget', codes)                                          # the edit feeds uncertainty budgets
        self.assertTrue(rep.can_save)
        row_warn = [i for i in rep.warnings if i.code == 'raw']
        self.assertEqual(rep.worst('rows', row_warn[0].target), 'warn')

    def test_copied_row_that_was_not_edited_warns(self):
        d = self.doc()
        new = d.add_range_after(d.ranges()[0][1])
        rep = se.validate(d)
        self.assertEqual([i.code for i in rep.row_issues(d.uid(new))], ['new-same'])
        self.assertEqual(rep.worst('rows', d.uid(new)), 'warn')

    def test_sheet_check_news_are_reported_for_the_row(self):
        d = self.doc()
        r = d.ranges()[1][1]
        d.edit_cell(d.lines()[1].iid, 'span', '5 to 6 A')                       # does not match the printed range (20 to 120) A
        rep = se.validate(d)
        self.assertTrue([i for i in rep.row_issues(d.uid(r)) if i.code == 'sheet-check'], [i.message for i in rep.issues])

    def test_confidence_change_is_reported(self):
        d = self.doc()
        d.edit_info('confidence_pct', '99')
        rep = se.validate(d)
        self.assertEqual(rep.checks[2], ('ok', 'Confidence 99 % gives divisor 2.576'))
        self.assertIn('budget', {i.code for i in rep.issues})


class Pipeline(Sandbox):
    def test_save_writes_atomically_documents_and_reads_back(self):
        d = self.edited_doc()
        before = (self.sd / COIL).read_bytes()
        res = self.save(d)
        after = (self.sd / COIL).read_bytes()
        self.assertEqual(after, d.raw)                                              # the document was rebased on what was written
        self.assertNotEqual(before, after)
        self.assertEqual(json.loads(after)['functions'][0]['ranges'][0]['resolution'], 0.01)
        e = elog.entries(COIL, self.db)[0]
        self.assertEqual((e['id'], e['kind'], e['edited_by'], e['reason'], e['source']), (res.edit_id, 'edit', 'Mike', 'test edit', 'unit test'))
        self.assertEqual((e['sha_before'], e['sha_after']), (se.sha256_bytes(before), se.sha256_bytes(after)))
        self.assertEqual([c['field'] for c in e['diff']], ['Resolution', 'Resolution source'])
        self.assertEqual(elog.before_bytes(e['id'], self.db), before)
        self.assertEqual(list(self.sd.glob('.spec_edit_*')), [])                    # no temporary file left behind
        self.assertEqual(d.diff(), [])                                              # nothing pending after the save

    def test_backup_names_follow_the_repo_convention(self):
        d = self.edited_doc()
        r1 = self.save(d)
        self.assertEqual(r1.backup.name, 'a2la_5500a_coil_standard_backup_v01.json')
        self.assertEqual(r1.backup.read_bytes(), SHEETS[0].read_bytes() if SHEETS[0].name == COIL else (ROOT / 'specs' / 'standards' / COIL).read_bytes())
        d.edit_cell(d.lines()[0].iid, 'page', '10')
        r2 = self.save(d)
        self.assertEqual(r2.backup.name, 'a2la_5500a_coil_standard_backup_v02.json')
        self.assertEqual(eio.next_backup(COIL, self.bk).name, 'a2la_5500a_coil_standard_backup_v03.json')
        d.edit_cell(d.lines()[0].iid, 'page', '11')
        r3 = self.save(d, backup=False)
        self.assertIsNone(r3.backup)
        self.assertEqual(sorted(p.name for p in self.bk.iterdir()), ['a2la_5500a_coil_standard_backup_v01.json', 'a2la_5500a_coil_standard_backup_v02.json'])
        self.assertEqual(elog.entries(COIL, self.db)[0]['backup_file'], '')

    def test_required_fields(self):
        d = self.edited_doc()
        for kw in ({'reason': ' '}, {'source': ''}, {'edited_by': '  '}):
            with self.assertRaises(eio.SaveError):
                self.save(d, **kw)
        self.assertEqual((self.sd / COIL).read_bytes(), (ROOT / 'specs' / 'standards' / COIL).read_bytes())
        self.assertEqual(elog.entries(COIL, self.db), [])

    def test_errors_block_saving(self):
        d = self.doc()
        d.edit_cell(d.lines()[2].iid, 'notes', '99')
        with self.assertRaises(eio.SaveError) as cm:
            self.save(d)
        self.assertIn('note 99 does not exist', str(cm.exception))
        self.assertEqual(elog.entries(COIL, self.db), [])

    def test_nothing_to_save(self):
        with self.assertRaises(eio.SaveError):
            self.save(self.doc())

    def test_file_changed_since_it_was_opened_is_not_overwritten(self):
        d = self.edited_doc()
        path = self.sd / COIL
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaises(eio.SaveError):
            self.save(d)
        self.assertEqual(elog.entries(COIL, self.db), [])

    def test_write_is_read_back_and_a_mismatch_restores_the_file(self):
        d = self.edited_doc()
        before = (self.sd / COIL).read_bytes()
        calls = []

        def bad_writer(path, raw):
            calls.append(path.name)
            eio.atomic_write(path, raw[:-5] + b'XXXX\n')                           # what lands on disk is not what was intended
        with self.assertRaises(eio.SaveError) as cm:
            self.save(d, writer=bad_writer)
        self.assertIn('read back', str(cm.exception))
        self.assertFalse(cm.exception.file_changed)                                 # it was put back
        self.assertEqual((self.sd / COIL).read_bytes(), before)
        self.assertEqual(calls, [COIL])                                              # the write itself was attempted once, never retried
        self.assertEqual(elog.entries(COIL, self.db), [])                           # an edit that did not happen is not logged
        self.assertTrue(d.diff())                                                    # the pending changes are still in the editor

    def test_write_error_leaves_the_file_alone_and_is_not_retried(self):
        d = self.edited_doc()
        before = (self.sd / COIL).read_bytes()
        calls = []

        def failing(path, raw):
            calls.append(1)
            raise OSError('disk full')
        with self.assertRaises(eio.SaveError) as cm:
            self.save(d, writer=failing)
        self.assertIn('disk full', str(cm.exception))
        self.assertEqual(len(calls), 1)
        self.assertEqual((self.sd / COIL).read_bytes(), before)

    def test_if_the_log_cannot_be_written_the_file_goes_back(self):
        d = self.edited_doc()
        before = (self.sd / COIL).read_bytes()
        with self.assertRaises(eio.SaveError):
            self.save(d, db_path=self.tmp / 'no_such_folder' / 'x.sqlite3')
        self.assertEqual((self.sd / COIL).read_bytes(), before)                     # an undocumented edit never stays

    def test_log_is_append_only(self):
        self.save(self.edited_doc())
        con = sqlite3.connect(self.db)
        for sql in ('UPDATE spec_edits SET reason="x"', 'DELETE FROM spec_edits', 'UPDATE spec_edit_events SET detail="x"', 'DELETE FROM spec_edit_events'):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                con.execute(sql)
        con.close()
        self.assertEqual(elog.count(COIL, self.db), 1)

    def test_only_additive_tables_and_calibration_database_untouched(self):
        con = sqlite3.connect(self.db)
        before = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
        con.close()
        self.save(self.edited_doc())
        con = sqlite3.connect(self.db)
        after = {r[0]: r[1] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)           # no existing table changed
        self.assertEqual(sorted(set(after) - set(before)), ['spec_edit_events', 'spec_edits', 'sqlite_sequence'] if 'sqlite_sequence' not in before else ['spec_edit_events', 'spec_edits'])
        self.assertEqual(list(self.tmp.rglob('calibration_procedures.sqlite3')), [])

    def test_last_editor_is_the_default_name(self):
        self.assertEqual(elog.last_editor(self.db), '')
        self.save(self.edited_doc(), edited_by='Dana')
        self.assertEqual(elog.last_editor(self.db), 'Dana')

    def test_restore_is_itself_a_documented_edit(self):
        original = (self.sd / COIL).read_bytes()
        d = self.edited_doc()
        r1 = self.save(d)
        edited = (self.sd / COIL).read_bytes()
        with self.assertRaises(eio.SaveError):
            eio.restore_edit(r1.edit_id, spec_dir=self.sd, edited_by='Mike', reason='', db_path=self.db, backup_dir=self.bk)
        r2 = eio.restore_edit(r1.edit_id, spec_dir=self.sd, edited_by='Mike', reason='wrong value', db_path=self.db, backup_dir=self.bk)
        self.assertEqual((self.sd / COIL).read_bytes(), original)
        es = elog.entries(COIL, self.db)
        self.assertEqual([(e['id'], e['kind'], e['restored_from']) for e in es], [(r2.edit_id, 'restore', r1.edit_id), (r1.edit_id, 'edit', None)])       # nothing rewritten, one entry added
        self.assertEqual((es[0]['sha_before'], es[0]['sha_after']), (se.sha256_bytes(edited), se.sha256_bytes(original)))
        self.assertEqual(es[0]['source'], f'{eio.RESTORE_SOURCE} {r1.edit_id}')
        self.assertTrue(es[0]['diff'])
        self.assertEqual(es[1], elog.entry(r1.edit_id, self.db))                    # the original entry is untouched
        with self.assertRaises(eio.SaveError):                                      # already as it was
            eio.restore_edit(r1.edit_id, spec_dir=self.sd, edited_by='Mike', reason='again', db_path=self.db, backup_dir=self.bk)
        r3 = eio.restore_edit(r2.edit_id, spec_dir=self.sd, edited_by='Mike', reason='undo the undo', db_path=self.db, backup_dir=self.bk)          # a restore can be restored
        self.assertEqual((self.sd / COIL).read_bytes(), edited)
        self.assertEqual(elog.count(COIL, self.db), 3)
        self.assertEqual(r3.kind, 'restore')

    def test_restore_works_without_the_backup_file(self):
        original = (self.sd / COIL).read_bytes()
        r1 = self.save(self.edited_doc(), backup=False)
        eio.restore_edit(r1.edit_id, spec_dir=self.sd, edited_by='Mike', reason='back', db_path=self.db, backup_dir=self.bk)
        self.assertEqual((self.sd / COIL).read_bytes(), original)

    def test_hand_edit_marker_states(self):
        path = self.sd / COIL
        self.assertEqual(eio.sheet_state(path, self.db)['state'], 'as built')
        r1 = self.save(self.edited_doc())
        st = eio.sheet_state(path, self.db)
        self.assertEqual((st['state'], st['edits']), ('edited by hand', 1))
        self.assertIn('Running build_coil_standard.py again would overwrite them', eio.state_text(st))
        eio.restore_edit(r1.edit_id, spec_dir=self.sd, edited_by='Mike', reason='back', db_path=self.db, backup_dir=self.bk)
        self.assertEqual(eio.sheet_state(path, self.db)['state'], 'back to as built')
        self.save(se.SpecDoc.load(path).__class__.load(path) if False else self._edit_again(path))
        self.assertEqual(eio.sheet_state(path, self.db)['state'], 'edited by hand')
        path.write_bytes((ROOT / 'specs' / 'standards' / COIL).read_bytes().replace(b'07/07/2026', b'08/08/2026'))        # a builder re-run, or anything else
        st = eio.sheet_state(path, self.db)
        self.assertEqual(st['state'], 'changed outside')
        self.assertIn('Changed outside the editor', eio.state_text(st))

    def _edit_again(self, path):
        d = se.SpecDoc.load(path)
        d.edit_cell(d.lines()[1].iid, 'page', '77')
        return d

    def test_compare_two_versions_of_a_file(self):
        a = json.loads((ROOT / 'specs' / 'standards' / COIL).read_text(encoding='utf-8'))
        b = json.loads(json.dumps(a))
        b['functions'][0]['ranges'][1]['specs'][0]['abs'] = 0.5
        b['standard']['revision'] = 'x'
        del b['notes']['3']
        cs = se.compare_data(a, b)
        self.assertEqual(sorted((c.op, c.area, c.label) for c in cs), [('remove', 'notes', 'Note removed'), ('set', 'info', 'revision'), ('set', 'rows', 'Floor (abs)')])
        self.assertEqual(se.compare_data(a, a), [])


class Rebuild(Sandbox):
    def sid(self):
        return next(s['id'] for s in sm.standards(self.db) if s['model'] == 'A2LA-5500A-COIL')

    def test_rebuild_updates_rows_keeps_ids_assets_divisor_and_database_only_edits(self):
        sid = self.sid()
        sm.set_assets(sid, [('A1', 'S1')], path=self.db)
        sm.set_standard_field(sid, 'divisor', 2.0, who='x', reason='r', path=self.db)
        rows = sm.rows_of(sid, path=self.db)
        sm.update_row(rows[1]['id'], {'resolution': 0.5}, who='x', reason='r', path=self.db)          # an edit made in Standards Specs (database only)
        ids = [r['id'] for r in rows]
        d = self.doc()
        d.edit_cell(d.lines()[0].iid, 'res', '0.01 A')
        d.edit_cell(d.lines()[2].iid, 'abs', '0.09 A')
        res = self.save(d)
        self.assertTrue(res.rebuild.done, res.rebuild.message)
        new = sm.rows_of(sid, path=self.db)
        self.assertEqual([r['id'] for r in new], ids)                               # rows keep their ids (so the change log still points at them)
        self.assertEqual(new[0]['resolution'], 0.01)
        self.assertEqual(new[1]['resolution'], 0.5)                                 # the Standards Specs edit survived
        self.assertEqual(new[1]['edited'], 1)
        self.assertEqual(new[2]['specs'][0]['abs'], 0.09)
        self.assertEqual(sm.assets_of(sid, path=self.db), [('A1', 'S1')])
        self.assertEqual(sm.StandardSpec(sid, self.db).divisor()[0], 2.0)
        self.assertEqual([s['id'] for s in sm.standards(self.db) if s['model'] == 'A2LA-5500A-COIL'], [sid])
        self.assertEqual(elog.events(res.edit_id, self.db)[0]['event'], 'sheet rebuilt')
        self.assertTrue([r for r in sm.log_for(sid, path=self.db) if r[2] == 'sheet_rebuild'])

    def test_an_edit_of_the_same_field_wins_over_the_database_edit_and_is_logged(self):
        sid = self.sid()
        sm.update_row(sm.rows_of(sid, path=self.db)[0]['id'], {'resolution': 0.5}, who='x', reason='r', path=self.db)
        d = self.doc()
        d.edit_cell(d.lines()[0].iid, 'res', '0.01 A')
        res = self.save(d)
        self.assertEqual(sm.rows_of(sid, path=self.db)[0]['resolution'], 0.01)
        self.assertTrue(res.rebuild.replaced)
        self.assertTrue(any('row 1 resolution' in x for x in res.rebuild.replaced), res.rebuild.replaced)
        self.assertTrue([r for r in sm.log_for(sid, path=self.db) if r[2] == 'sheet_rebuild_replaced'])

    def test_rows_added_and_removed_in_the_database(self):
        sid = self.sid()
        d = self.doc()
        new = d.add_range_after(d.ranges()[0][1])
        d.edit_field(new, 'label', '(1 to 2) A')
        d.edit_cell(d.line(f'L{d.uid(new)}_{d.uid(new["specs"][0])}').iid, 'rel', '1 ppm')
        d.delete_range(d.ranges()[4][1])
        res = self.save(d)
        self.assertEqual((res.rebuild.added, res.rebuild.removed), (1, 1))
        labels = [r['label'] for r in sm.rows_of(sid, path=self.db)]
        self.assertEqual(len(labels), 5)
        self.assertIn('(1 to 2) A', labels)

    def test_header_edit_reaches_the_database(self):
        sid = self.sid()
        d = self.doc()
        d.edit_info('confidence_pct', '99')
        d.edit_info('revision', '10/2026')
        self.save(d)
        info = next(s for s in sm.standards(self.db) if s['id'] == sid)
        self.assertEqual((info['confidence_pct'], info['revision']), (99.0, '10/2026'))
        self.assertEqual(sm.StandardSpec(sid, self.db).divisor()[0], 2.576)

    def test_rebuild_is_skipped_when_the_database_cannot_be_matched_and_has_edits(self):
        sid = self.sid()
        rows = sm.rows_of(sid, path=self.db)
        sm.update_row(rows[0]['id'], {'resolution': 0.5}, who='x', reason='r', path=self.db)
        con = sqlite3.connect(self.db)
        con.execute('DELETE FROM spec_rows WHERE id=?', (rows[3]['id'],))              # the database no longer holds the file as it was
        con.commit()
        con.close()
        d = self.doc()
        d.edit_cell(d.lines()[1].iid, 'page', '33')
        res = self.save(d)
        self.assertFalse(res.rebuild.done)
        self.assertIn('left alone', res.rebuild.message)
        self.assertEqual(sm.rows_of(sid, path=self.db)[0]['resolution'], 0.5)             # nothing of the person's was thrown away
        self.assertEqual(json.loads((self.sd / COIL).read_text(encoding='utf-8'))['functions'][0]['ranges'][1]['page'], 33)         # the file is saved anyway

    def test_standard_not_in_the_database(self):
        d = self.doc('a2la_light_standard.json')
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM standards WHERE model='A2LA-LIGHT'")
        con.commit()
        con.close()
        d.edit_cell(d.lines()[0].iid, 'page', '44')
        res = self.save(d)
        self.assertFalse(res.rebuild.done)
        self.assertIn('not loaded', res.rebuild.message)

    def test_no_rebuild_when_not_asked(self):
        d = self.edited_doc()
        res = self.save(d, rebuild=False)
        self.assertIsNone(res.rebuild)
        self.assertIsNone(next(r for r in sm.rows_of(self.sid(), path=self.db))['resolution'])
        self.assertEqual(elog.events(res.edit_id, self.db), [])

    def test_restore_rebuilds_too(self):
        r1 = self.save(self.edited_doc())
        self.assertEqual(sm.rows_of(self.sid(), path=self.db)[0]['resolution'], 0.01)
        eio.restore_edit(r1.edit_id, spec_dir=self.sd, edited_by='Mike', reason='back', db_path=self.db, backup_dir=self.bk)
        self.assertIsNone(sm.rows_of(self.sid(), path=self.db)[0]['resolution'])


class Exports(Sandbox):
    def test_csv(self):
        self.save(self.edited_doc())
        dest = self.tmp / 'h.csv'
        self.assertEqual(eio.export_history_csv(COIL, dest, self.db), 1)
        text = dest.read_text(encoding='utf-8-sig')
        self.assertIn('Mike', text)
        self.assertIn('test edit', text)
        self.assertIn('Resolution', text)

    def test_pdf(self):
        if not eio.pdf_available():
            self.skipTest('reportlab is not installed')
        self.save(self.edited_doc())
        dest = self.tmp / 'h.pdf'
        self.assertEqual(eio.export_history_pdf(COIL, dest, self.db, 'A2LA-5500A-COIL', eio.state_text(eio.sheet_state(self.sd / COIL, self.db))), 1)
        self.assertTrue(dest.read_bytes().startswith(b'%PDF'))


class Layout(unittest.TestCase):
    def test_file_with_other_formatting_is_flagged_not_silently_reformatted(self):
        raw = json.dumps(json.loads(SHEETS[0].read_text(encoding='utf-8')), indent=3).encode('utf-8')
        d = se.SpecDoc.from_bytes('x_standard.json', raw)
        self.assertFalse(d.style.exact)
        self.assertIn('layout', {i.code for i in se.validate(d).warnings})

    def test_not_a_sheet(self):
        with self.assertRaises(se.SpecFileError):
            se.SpecDoc.from_bytes('x.json', b'{"a": 1}')
        with self.assertRaises(se.SpecFileError):
            se.SpecDoc.from_bytes('x.json', b'not json')


if __name__ == '__main__':
    unittest.main()
