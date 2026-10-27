"""Procedure Generator model (procedure_generator.py): modes and requirements, the Build gate text, uploads (copy, hash, remove), storage idempotence, row validation,
the review gating.  No Qt, no network, no instrument I/O; the manual is a PDF written by reportlab in the test.
Run:  python -m unittest tests.test_procedure_generator"""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import pg_fixtures as fx  # noqa: E402
import procedure_generator as pg  # noqa: E402
import procedure_generator_ai as ai  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.store = pg.Store(root=self.d / 'gen', registry=self.d / 'reg.sqlite3')
        self.p = self.store.create('Meter 100', 'tester')
        self.p.make, self.p.model = 'Acme', 'M100'
        self.pdf = fx.make_pdf(self.d / 'manual.pdf')

    def with_rows(self, mode=pg.ONEWAY, accept=True, check=True):
        p = self.p
        p.mode = mode
        f = self.store.add_file(p, self.pdf, pg.ROLE_SPEC)
        pg.set_pages(p, f.id, 1, 2)
        rows = ai._parse_rows({'rows': fx.good_items()}, [(f.id, 1)], [])
        pg.add_rows(p, rows)
        if accept:
            for r in p.rows:
                pg.set_status(p, r.id, pg.STATUS_ACCEPTED)
        if check:
            pg.confirm_page(p, f.id, 1)
        return f


class Requirements(Base):
    def keys(self, p=None):
        return [r.key for r in pg.missing(p or self.p)]

    def test_nothing_is_required_beyond_the_basics_before_a_mode_is_chosen(self):
        self.p.name = self.p.model = ''
        self.assertEqual(self.keys(), ['name', 'model', 'mode'])

    def test_manual_and_oneway_need_only_a_spec_sheet(self):
        for mode in (pg.MANUAL, pg.ONEWAY):
            p = self.store.create('Meter ' + mode, 'tester')
            p.make, p.model, p.mode = 'Acme', 'M100', mode
            self.assertEqual(self.keys(p), ['spec'], mode)
            self.assertEqual([r.key for r in pg.requirements(p)], ['name', 'model', 'mode', 'spec'])
            self.store.add_file(p, self.pdf, pg.ROLE_SPEC)
            self.assertEqual(self.keys(p), [], mode)

    def test_twoway_needs_a_programming_manual_for_each_instrument_and_a_photo(self):
        p = self.p
        p.mode = pg.TWOWAY
        self.assertEqual(self.keys(), ['spec', 'instruments', 'photo'])
        self.store.add_file(p, self.pdf, pg.ROLE_SPEC)
        p.instruments = [pg.Instrument('u', 'Acme M100', 'uut'), pg.Instrument('c', 'Fluke 5522A', 'standard')]
        self.assertEqual(self.keys(), ['prog:u', 'prog:c', 'photo'])
        self.store.add_file(p, fx.make_pdf(self.d / 'prog_u.pdf', 2, 'Prog M100'), pg.ROLE_PROG, 'u')
        self.assertEqual(self.keys(), ['prog:c', 'photo'])
        self.store.add_file(p, fx.make_pdf(self.d / 'prog_c.pdf', 2, 'Prog 5522A'), pg.ROLE_PROG, 'c')
        self.assertEqual(self.keys(), ['photo'])
        self.store.add_file(p, fx.make_png(self.d / 'hook.png'), pg.ROLE_PHOTO)
        self.assertEqual(self.keys(), [])

    def test_a_programming_manual_must_belong_to_a_listed_instrument(self):
        self.p.mode = pg.TWOWAY
        with self.assertRaises(pg.UploadError):
            self.store.add_file(self.p, self.pdf, pg.ROLE_PROG, 'nobody')

    def test_the_photo_is_optional_in_manual_mode_and_never_required(self):
        self.p.mode = pg.MANUAL
        self.assertNotIn('photo', [r.key for r in pg.requirements(self.p)])
        self.store.add_file(self.p, fx.make_jpg(self.d / 'x.jpg'), pg.ROLE_PHOTO)        # stored, offered as the reference image
        self.assertEqual(len(self.p.files_of(pg.ROLE_PHOTO)), 1)


class BuildGate(Base):
    def test_the_gate_names_exactly_what_is_missing(self):
        g = pg.gate(self.p)
        self.assertFalse(g.can_click)
        self.assertIn('Choose how the procedure is automated', g.text)
        self.p.mode = pg.TWOWAY
        self.p.instruments = [pg.Instrument('u', 'Acme M100', 'uut')]
        g = pg.gate(self.p)
        self.assertEqual(g.stage, 'requirements')
        for need in ('Spec sheet or manual', 'Programming manual (PDF) for Acme M100', 'Hook-up photo'):
            self.assertIn(need, g.text)

    def test_twoway_with_everything_uploaded_says_coming_and_stays_saved(self):
        p = self.p
        p.mode = pg.TWOWAY
        self.store.add_file(p, self.pdf, pg.ROLE_SPEC)
        p.instruments = [pg.Instrument('u', 'Acme M100', 'uut')]
        self.store.add_file(p, fx.make_pdf(self.d / 'prog.pdf', 2), pg.ROLE_PROG, 'u')
        self.store.add_file(p, fx.make_png(self.d / 'hook.png'), pg.ROLE_PHOTO)
        g = pg.gate(p)
        self.assertEqual((g.stage, g.can_click), ('coming', True))
        self.assertIn('coming', g.text)
        import procedure_generator_build as bd
        res = bd.build(p, self.store, 'tester', registry=self.d / 'reg.sqlite3', root=self.d / 'us')
        self.assertTrue(res.coming)
        self.assertFalse(res.ok)
        self.assertIn('Two-way generation is coming', res.message)
        self.store.save(p)
        again = self.store.load(p.id)
        self.assertEqual((again.mode, len(again.files), len(again.instruments)), (pg.TWOWAY, 3, 1))     # the project is kept, complete
        self.assertFalse((self.d / 'us').exists())                                                           # nothing was built

    def test_gate_stages_in_the_order_the_person_works(self):
        p = self.p
        p.mode = pg.ONEWAY
        f = self.store.add_file(p, self.pdf, pg.ROLE_SPEC)
        self.assertEqual(pg.gate(p).stage, 'pages')
        pg.set_pages(p, f.id, 1, 2)
        self.assertEqual(pg.gate(p).stage, 'rows')
        pg.add_rows(p, ai._parse_rows({'rows': fx.good_items()}, [(f.id, 1)], []))
        g = pg.gate(p)
        self.assertEqual((g.stage, g.can_click), ('undecided', False))
        self.assertIn('3 row(s) are not decided', g.text)
        for r in p.rows:
            pg.set_status(p, r.id, pg.STATUS_ACCEPTED)
        g = pg.gate(p)
        self.assertEqual(g.stage, 'unchecked')
        self.assertIn('p. 1', g.text)
        pg.confirm_page(p, f.id, 1)
        self.assertEqual((pg.gate(p).stage, pg.gate(p).can_click), ('ready', True))

    def test_every_row_rejected_cannot_build(self):
        self.with_rows(accept=False)
        for r in self.p.rows:
            pg.set_status(self.p, r.id, pg.STATUS_REJECTED)
        self.assertEqual(pg.gate(self.p).stage, 'rows')
        self.assertFalse(pg.gate(self.p).can_click)

    def test_cannot_build_without_confirming_the_page_and_editing_unconfirms_it(self):
        self.with_rows(check=False)
        self.assertFalse(pg.gate(self.p).can_click)
        self.assertEqual(pg.gate(self.p).stage, 'unchecked')
        pg.confirm_page(self.p, self.p.files[0].id, 1)
        self.assertTrue(pg.gate(self.p).can_click)
        pg.edit_row(self.p, self.p.rows[0].id, high='5.006 V')                    # a number changed after the check: the check no longer holds
        self.assertEqual(pg.gate(self.p).stage, 'unchecked')
        self.assertEqual(self.p.rows[0].status, pg.STATUS_EDITED)
        self.assertEqual(self.p.rows[0].model_values['high'], '5.005 V')           # what the reader returned is kept
        pg.confirm_page(self.p, self.p.files[0].id, 1)
        self.assertTrue(pg.gate(self.p).can_click)

    def test_accepting_another_row_needs_the_page_confirmed_again(self):
        self.with_rows(accept=False, check=False)
        for r in self.p.rows[:2]:
            pg.set_status(self.p, r.id, pg.STATUS_ACCEPTED)
        pg.confirm_page(self.p, self.p.files[0].id, 1)
        pg.set_status(self.p, self.p.rows[2].id, pg.STATUS_ACCEPTED)
        self.assertEqual(pg.gate(self.p).stage, 'unchecked')

    def test_a_row_with_an_error_blocks_the_build(self):
        self.with_rows()
        pg.edit_row(self.p, self.p.rows[0].id, low='5.010 V')                      # low above high
        pg.confirm_page(self.p, self.p.files[0].id, 1)
        g = pg.gate(self.p)
        self.assertEqual((g.stage, g.can_click), ('errors', False))
        self.assertIn('low limit', g.text)


class Uploads(Base):
    def test_a_file_is_copied_hashed_and_the_original_is_untouched(self):
        before = self.pdf.read_bytes()
        mtime = self.pdf.stat().st_mtime_ns
        f = self.store.add_file(self.p, self.pdf, pg.ROLE_SPEC)
        stored = self.store.file_path(self.p, f.id)
        self.assertNotEqual(stored, self.pdf)
        self.assertEqual(stored.read_bytes(), before)
        self.assertEqual(f.sha256, hashlib.sha256(before).hexdigest())
        self.assertEqual((f.size, f.pages, f.original, f.role), (len(before), 4, 'manual.pdf', pg.ROLE_SPEC))
        self.assertEqual(self.pdf.read_bytes(), before)
        self.assertEqual(self.pdf.stat().st_mtime_ns, mtime)
        self.assertIn(self.p.id, str(stored))

    def test_the_same_file_twice_is_refused_not_duplicated(self):
        self.store.add_file(self.p, self.pdf, pg.ROLE_SPEC)
        with self.assertRaises(pg.UploadError) as cm:
            self.store.add_file(self.p, self.pdf, pg.ROLE_SPEC)
        self.assertIn('already in the project', str(cm.exception))
        self.assertEqual(len(self.p.files), 1)
        self.assertEqual(len(list(self.store.files_dir(self.p.id).iterdir())), 1)         # no stray .part file

    def test_wrong_kinds_are_refused_with_a_reason(self):
        txt = self.d / 'notes.txt'
        txt.write_text('hello')
        fake = self.d / 'fake.pdf'
        fake.write_bytes(b'this is not a pdf at all' * 10)
        png_named_pdf = self.d / 'pic.pdf'
        fx.make_png(self.d / 'pic.png')
        png_named_pdf.write_bytes((self.d / 'pic.png').read_bytes())
        empty = self.d / 'empty.pdf'
        empty.write_bytes(b'')
        for path, role, word in ((txt, pg.ROLE_SPEC, 'must be PDF'), (fake, pg.ROLE_SPEC, 'not a PDF'), (png_named_pdf, pg.ROLE_SPEC, 'not a PDF'), (empty, pg.ROLE_SPEC, 'empty'),
                                 (self.pdf, pg.ROLE_PHOTO, 'PNG or JPG'), (self.d / 'missing.pdf', pg.ROLE_SPEC, 'cannot be read')):
            with self.assertRaises(pg.UploadError, msg=str(path)) as cm:
                self.store.add_file(self.p, path, role)
            self.assertIn(word, str(cm.exception))
        jpg_named_png = self.d / 'x.png'
        fx.make_jpg(self.d / 'x.jpg')
        jpg_named_png.write_bytes((self.d / 'x.jpg').read_bytes())
        with self.assertRaises(pg.UploadError):
            self.store.add_file(self.p, jpg_named_png, pg.ROLE_PHOTO)
        self.assertEqual(self.p.files, [])

    def test_photo_png_and_jpg_are_accepted(self):
        a = self.store.add_file(self.p, fx.make_png(self.d / 'a.png'), pg.ROLE_PHOTO)
        b = self.store.add_file(self.p, fx.make_jpg(self.d / 'b.jpg'), pg.ROLE_PHOTO)
        self.assertEqual((a.pages, b.pages), (1, 1))

    def test_remove_deletes_our_copy_and_what_hangs_on_it_but_never_the_original(self):
        f = self.with_rows()
        stored = self.store.file_path(self.p, f.id)
        self.assertTrue(stored.is_file())
        self.assertTrue(self.store.remove_file(self.p, f.id))
        self.assertFalse(stored.exists())
        self.assertTrue(self.pdf.is_file())
        self.assertEqual((self.p.files, self.p.rows, self.p.pages, self.p.checked), ([], [], {}, []))
        self.assertEqual(self.store.load(self.p.id).files, [])

    def test_a_file_a_procedure_was_built_from_cannot_be_removed(self):
        f = self.with_rows()
        self.p.build = dict(uid='x', title='T', source_files={'manual.pdf': f.sha256})
        with self.assertRaises(pg.UploadError) as cm:
            self.store.remove_file(self.p, f.id)
        self.assertIn('source', str(cm.exception))
        self.assertEqual(len(self.p.files), 1)

    def test_page_count_helper_and_pages_range_validation(self):
        f = self.store.add_file(self.p, self.pdf, pg.ROLE_SPEC)
        self.p.mode = pg.MANUAL
        self.assertEqual(pg.set_pages(self.p, f.id, 2, 3), [2, 3])
        for first, last in ((0, 1), (3, 2), (1, 5)):
            with self.assertRaises(ValueError):
                pg.set_pages(self.p, f.id, first, last)


class Storage(Base):
    def test_save_is_idempotent_and_load_round_trips(self):
        self.with_rows()
        self.store.save(self.p)
        first = self.store.load(self.p.id)
        updated = first.updated
        con = sqlite3.connect(self.d / 'reg.sqlite3')
        blob1 = con.execute('SELECT state_json FROM generator_projects WHERE id=?', (self.p.id,)).fetchone()[0]
        con.close()
        for _ in range(3):
            self.store.save(self.store.load(self.p.id))
        con = sqlite3.connect(self.d / 'reg.sqlite3')
        blob2 = con.execute('SELECT state_json FROM generator_projects WHERE id=?', (self.p.id,)).fetchone()[0]
        n = con.execute('SELECT COUNT(*) FROM generator_projects').fetchone()[0]
        con.close()
        self.assertEqual((blob1, n), (blob2, 1))
        self.assertEqual(self.store.load(self.p.id).updated, updated)
        self.assertEqual(self.store.load(self.p.id).to_dict(), first.to_dict())
        self.assertEqual(len(self.store.list()), 1)

    def test_schema_creation_twice_and_only_new_tables(self):
        self.store.save(self.p)
        pg.Store(root=self.d / 'gen', registry=self.d / 'reg.sqlite3').save(self.p)
        con = sqlite3.connect(self.d / 'reg.sqlite3')
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertEqual(tables, {'generator_projects'})

    def test_files_live_under_the_project_folder_in_the_data_folder_only(self):
        self.store.add_file(self.p, self.pdf, pg.ROLE_SPEC)
        files = [p for p in (self.d / 'gen').rglob('*') if p.is_file()]
        self.assertTrue(files)
        self.assertTrue(all(self.p.id in str(f) for f in files))

    def test_default_locations_follow_the_data_folder_and_calibration_procedures_is_never_touched(self):
        data = self.d / 'data'
        old = os.environ.get('CALSUITE_DATA')
        os.environ['CALSUITE_DATA'] = str(data)
        try:
            st = pg.Store()
            p = st.create('X', 'me')
            st.add_file(p, self.pdf, pg.ROLE_SPEC)
            self.assertEqual(st.registry, data / 'lab_registry.sqlite3')
            self.assertTrue((data / 'generator' / p.id / 'files').is_dir())
            self.assertFalse((data / 'calibration_procedures.sqlite3').exists())
        finally:
            if old is None:
                os.environ.pop('CALSUITE_DATA', None)
            else:
                os.environ['CALSUITE_DATA'] = old

    def test_delete_is_soft_and_hides_the_project(self):
        self.store.save(self.p)
        self.assertTrue(self.store.delete(self.p.id))
        self.assertEqual(self.store.list(), [])
        self.assertIsNone(self.store.load(self.p.id))

    def test_a_damaged_registry_gives_empty_results_not_a_crash(self):
        bad = pg.Store(root=self.d / 'g2', registry=self.d)           # a folder is not a database
        self.assertEqual(bad.list(), [])
        self.assertIsNone(bad.load('gp-x'))


class Validation(Base):
    def row(self, **kw):
        base = dict(file_id='f', page=1, function='DCV', nominal='5.000 V', low='4.995 V', high='5.005 V')
        base.update(kw)
        r = pg.Row('r1', **base)
        return r

    def flags(self, **kw):
        return {f.code: f for f in pg.validate_row(self.row(**kw))}

    def test_a_clean_row_has_no_flags(self):
        self.assertEqual(self.flags(), {})

    def test_reversed_limits_are_an_error(self):
        f = self.flags(low='5.005 V', high='4.995 V')
        self.assertEqual(f['limits_reversed'].level, 'error')

    def test_reversed_limits_across_prefixes_are_compared_in_decimal(self):
        f = self.flags(nominal='5 V', low='5100 mV', high='4.9 V')
        self.assertIn('limits_reversed', f)
        self.assertNotIn('limits_reversed', self.flags(nominal='5 V', low='4900 mV', high='5.1 V'))

    def test_unit_that_does_not_fit_the_kind_is_an_error(self):
        self.assertEqual(self.flags(function='DCI')['unit_mismatch'].level, 'error')           # volts on a current row
        self.assertEqual(self.flags(function='OHM2', nominal='100 ohm', low='99 V', high='101 ohm')['unit_mismatch'].level, 'error')

    def test_a_number_without_a_unit_is_an_error_never_a_silent_base_unit(self):
        f = self.flags(nominal='10', low='9.995', high='10.005')
        self.assertIn('no_unit', f)
        self.assertEqual(f['no_unit'].level, 'error')

    def test_micro_and_ohm_signs_and_ascii_spellings(self):
        self.assertEqual(self.flags(function='DCI', nominal='100 µA', low='99 µA', high='101 µA'), {})
        self.assertEqual(self.flags(function='DCI', nominal='100 uA', low='99 uA', high='101 uA'), {})
        self.assertEqual(self.flags(function='OHM2', nominal='1 kΩ', low='0.99 kΩ', high='1.01 kΩ'), {})
        self.assertEqual(self.flags(function='OHM2', nominal='1 kohm', low='990 ohm', high='1010 ohm'), {})

    def test_impossible_values(self):
        self.assertIn('negative', self.flags(function='OHM2', nominal='-5 ohm', low='-6 ohm', high='-4 ohm'))
        self.assertIn('frequency_value', self.flags(function='ACV', frequency='0 Hz'))
        self.assertIn('impossible', self.flags(nominal='9999999999999 V', low='9999999999998 V', high='9999999999999.5 V'))
        self.assertIn('nominal', self.flags(nominal=''))
        self.assertIn('nominal', self.flags(nominal='abc V'))

    def test_one_limit_or_none(self):
        self.assertEqual(self.flags(low='')['one_limit'].level, 'error')
        f = self.flags(low='', high='')
        self.assertEqual(f['no_limits'].level, 'error')

    def test_accuracy_instead_of_limits_is_a_warning_when_readable(self):
        f = self.flags(low='', high='', accuracy='0.05 % of reading + 2 counts')
        self.assertEqual(f['limits_from_accuracy'].level, 'warn')
        self.assertEqual(self.flags(low='', high='', accuracy='gibberish text')['accuracy_unreadable'].level, 'error')

    def test_nominal_outside_its_limits_is_a_warning(self):
        self.assertEqual(self.flags(nominal='6 V')['nominal_outside'].level, 'warn')

    def test_model_uncertainty_and_ac_without_frequency_are_warnings(self):
        f = self.flags(function='ACV', uncertain=True, note='6 or 8?')
        self.assertEqual(f['model_uncertain'].level, 'warn')
        self.assertIn('6 or 8?', f['model_uncertain'].text)
        self.assertEqual(f['no_frequency'].level, 'warn')

    def test_unknown_kind_missing_page_and_thermocouple_type(self):
        self.assertIn('bad_kind', self.flags(function='NOPE'))
        self.assertIn('no_page', self.flags(page=0))
        t = self.flags(function='TEMP', nominal='100 degC', low='99 degC', high='101 degC', tc_type='Z')
        self.assertEqual(t['tc_type'].level, 'error')
        t = self.flags(function='TEMP', nominal='100 degC', low='99 degC', high='101 degC')
        self.assertEqual(t['tc_missing'].level, 'warn')
        self.assertNotIn('tc_missing', self.flags(function='TEMP', nominal='100 degC', low='99 degC', high='101 degC', tc_type='k'))

    def test_a_page_outside_the_chosen_pages_is_an_error(self):
        f = self.with_rows()
        r = self.p.rows[0]
        self.assertEqual([x.code for x in pg.validate_row(r, self.p)], [])
        pg.edit_row(self.p, r.id, page=3)
        self.assertIn('page_not_selected', [x.code for x in pg.validate_row(self.p.rows[0], self.p)])

    def test_duplicates_are_flagged(self):
        self.with_rows()
        dup = pg.Row('', file_id=self.p.files[0].id, page=1, step='1-1', function='DCV', section='DC volts', range='10 V', nominal='5.000 V', low='4.995 V', high='5.005 V')
        pg.add_rows(self.p, [dup])
        self.assertIn('duplicate', [x.code for x in pg.validate_row(self.p.rows[0], self.p)])

    def test_unverified_list_carries_warnings_edits_and_typed_rows(self):
        self.with_rows()
        pg.edit_row(self.p, self.p.rows[0].id, nominal='5.00 V')
        self.p.rows[1].uncertain, self.p.rows[1].note = True, 'blurred'
        typed = pg.Row('', file_id=self.p.files[0].id, page=1, function='DCV', nominal='1 V', low='0.99 V', high='1.01 V', source='typed', status=pg.STATUS_ACCEPTED)
        pg.add_rows(self.p, [typed])
        text = '\n'.join(pg.unverified_list(self.p))
        self.assertIn('edited after the reader returned it', text)
        self.assertIn('blurred', text)
        self.assertIn('typed by hand', text)
        self.assertIn('p. 1', text)

    def test_rejected_rows_are_not_listed(self):
        self.with_rows()
        self.p.rows[1].uncertain = True
        pg.set_status(self.p, self.p.rows[1].id, pg.STATUS_REJECTED)
        self.assertNotIn('uncertain', '\n'.join(pg.unverified_list(self.p)))


class Json(Base):
    def test_state_is_plain_json(self):
        self.with_rows()
        text = json.dumps(self.p.to_dict())
        self.assertEqual(pg.Project.from_dict(json.loads(text)).to_dict(), self.p.to_dict())

    def test_no_secrets_in_the_project(self):
        os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-api03-SECRETSECRETSECRET1234'
        try:
            self.with_rows()
            self.store.save(self.p)
            blob = json.dumps(self.p.to_dict())
            self.assertNotIn('SECRETSECRET', blob)
            for f in (self.d / 'gen').rglob('*'):
                if f.is_file() and f.suffix in ('.json', '.txt'):
                    self.assertNotIn('SECRETSECRET', f.read_text(errors='ignore'))
            self.assertNotIn(b'SECRETSECRET', (self.d / 'reg.sqlite3').read_bytes())
        finally:
            os.environ.pop('ANTHROPIC_API_KEY', None)


if __name__ == '__main__':
    unittest.main()
