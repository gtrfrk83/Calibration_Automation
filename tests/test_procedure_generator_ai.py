"""Procedure Generator reading (procedure_generator_ai.py): what the API receives, the key, the capped retry.  The API client is a mock; no network.
Run:  python -m unittest tests.test_procedure_generator_ai"""
import base64
import json
import logging
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import pg_fixtures as fx  # noqa: E402
import procedure_generator as pg  # noqa: E402
import procedure_generator_ai as ai  # noqa: E402

KEY = 'sk-ant-api03-TOPSECRETKEYVALUE0123456789'


class Err(Exception):
    def __init__(self, msg='boom', status_code=None):
        super().__init__(msg)
        self.status_code = status_code
        self.message = msg


class APIConnectionError(Exception):
    pass


class Base(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.d / 'home'), 'USERPROFILE': str(self.d / 'home'), 'CALSUITE_DATA': str(self.d / 'data'), 'ANTHROPIC_API_KEY': KEY})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = pg.Store(root=self.d / 'gen', registry=self.d / 'reg.sqlite3')
        self.p = self.store.create('M', 'me')
        self.p.mode = pg.ONEWAY
        self.f = self.store.add_file(self.p, fx.make_pdf(self.d / 'm.pdf', 5), pg.ROLE_SPEC)
        self.sleeps = []

    def run_extract(self, client, first=1, last=1, **kw):
        return ai.extract(self.store, self.p, self.f.id, first, last, client_factory=lambda key: client, sleep=self.sleeps.append, **kw)


class Request(Base):
    def test_images_are_sent_never_text(self):
        c = fx.FakeClient([fx.FakeResponse(fx.good_items())])
        res = self.run_extract(c, 1, 2)
        req = c.requests[0]
        blocks = req['messages'][0]['content']
        images = [b for b in blocks if b['type'] == 'image']
        self.assertEqual(len(images), 2)
        for b in images:
            self.assertEqual(b['source']['media_type'], 'image/png')
            self.assertTrue(base64.b64decode(b['source']['data']).startswith(b'\x89PNG'))
        text = ' '.join(b['text'] for b in blocks if b['type'] == 'text')
        self.assertNotIn('4.995', text)                              # nothing extracted from the PDF's text layer
        self.assertNotIn('DC volts', text)
        self.assertEqual({b['type'] for b in blocks}, {'text', 'image'})
        self.assertEqual(res.requests, 1)

    def test_model_default_and_configurable(self):
        c = fx.FakeClient([fx.FakeResponse([])])
        self.run_extract(c)
        self.assertEqual(c.requests[0]['model'], 'claude-sonnet-5-5')
        ai.save_settings(model='claude-test-9')
        c = fx.FakeClient([fx.FakeResponse([])])
        self.run_extract(c)
        self.assertEqual(c.requests[0]['model'], 'claude-test-9')

    def test_forced_structured_tool_with_the_schema(self):
        c = fx.FakeClient([fx.FakeResponse([])])
        self.run_extract(c)
        req = c.requests[0]
        self.assertEqual(req['tool_choice'], {'type': 'tool', 'name': 'report_table_rows'})
        tool = req['tools'][0]
        self.assertEqual(tool['name'], 'report_table_rows')
        item = tool['input_schema']['properties']['rows']['items']
        for k in ('function_kind', 'nominal', 'low_limit', 'high_limit', 'accuracy', 'uncertain', 'image', 'tc_type', 'frequency'):
            self.assertIn(k, item['properties'])
        self.assertEqual(sorted(item['properties']['function_kind']['enum']), sorted(pg.GEN_KINDS))
        json.dumps(req)                                               # a plain JSON-able request

    def test_three_pages_per_request_and_the_page_mapping(self):
        c = fx.FakeClient([fx.FakeResponse([fx.model_item(1, '1', nominal='1 V', low='0.9 V', high='1.1 V')]),
                           fx.FakeResponse([fx.model_item(2, '2', nominal='2 V', low='1.9 V', high='2.1 V')])])
        res = self.run_extract(c, 1, 5)
        self.assertEqual(len(c.requests), 2)
        self.assertEqual([r.page for r in res.rows], [1, 5])         # image 2 of the 2nd request is page 5
        self.assertTrue(all(r.file_id == self.f.id and r.source == 'model' for r in res.rows))
        self.assertEqual(res.rows[0].model_values['high'], '1.1 V')

    def test_page_limits(self):
        c = fx.FakeClient([])
        for a, b in ((0, 1), (3, 9), (4, 2)):
            with self.assertRaises(ai.ExtractError):
                self.run_extract(c, a, b)
        self.assertEqual(c.requests, [])

    def test_an_image_number_we_did_not_send_is_kept_with_no_page(self):
        c = fx.FakeClient([fx.FakeResponse([fx.model_item(7, '1', nominal='1 V', low='0.9 V', high='1.1 V')])])
        r = self.run_extract(c).rows[0]
        self.assertEqual(r.page, 0)
        self.assertIn('no_page', [f.code for f in pg.validate_row(r)])

    def test_cut_off_or_no_tool_call_adds_nothing(self):
        for resp, word in ((fx.FakeResponse([], stop_reason='max_tokens'), 'cut off'),
                           (SimpleNamespace(content=[SimpleNamespace(type='text', text='hi')], stop_reason='end_turn', usage=fx.FakeUsage()), 'did not contain')):
            with self.assertRaises(ai.ExtractError) as cm:
                self.run_extract(fx.FakeClient([resp]))
            self.assertIn(word, str(cm.exception))

    def test_the_rendered_pages_are_cached_and_the_renderer_is_named(self):
        c = fx.FakeClient([fx.FakeResponse([]), fx.FakeResponse([])])
        self.run_extract(c)
        pngs = list(self.store.pages_dir(self.p.id, self.f.id).rglob('*.png'))
        self.assertTrue(pngs)
        mt = pngs[0].stat().st_mtime_ns
        self.run_extract(c)
        self.assertEqual(pngs[0].stat().st_mtime_ns, mt)
        self.assertTrue(ai.renderer_name())


class Retry(Base):
    def test_transient_errors_are_retried_up_to_a_cap(self):
        c = fx.FakeClient([APIConnectionError('down'), Err('busy', 529), fx.FakeResponse(fx.good_items())])
        res = self.run_extract(c)
        self.assertEqual((len(c.requests), res.attempts, len(res.rows)), (3, 3, 3))
        self.assertEqual(self.sleeps, [2.0, 5.0])
        self.assertEqual(c.requests[0], c.requests[2])                # the identical read-only request

    def test_cap_is_three_attempts(self):
        c = fx.FakeClient([Err('x', 503)] * 5)
        with self.assertRaises(ai.ExtractError) as cm:
            self.run_extract(c)
        self.assertEqual(len(c.requests), 3)
        self.assertIn('type the rows by hand', str(cm.exception))

    def test_non_transient_errors_are_not_retried(self):
        for code in (400, 401, 403, 404):
            c = fx.FakeClient([Err('nope', code), fx.FakeResponse([])])
            with self.assertRaises(ai.ExtractError):
                self.run_extract(c)
            self.assertEqual(len(c.requests), 1, code)
        self.assertEqual(self.sleeps, [])

    def test_classification(self):
        self.assertTrue(all(ai.is_transient(Err(status_code=c)) for c in (408, 409, 429, 500, 503, 529)))
        self.assertFalse(any(ai.is_transient(Err(status_code=c)) for c in (400, 401, 403, 404, 422)))
        self.assertTrue(ai.is_transient(APIConnectionError()))
        self.assertTrue(ai.is_transient(TimeoutError()))
        self.assertFalse(ai.is_transient(ValueError('x')))

    def test_friendly_messages(self):
        self.assertIn('key was refused', ai.friendly(Err(status_code=401), KEY))
        self.assertIn('model name', ai.friendly(Err(status_code=404), KEY))


class Key(Base):
    def test_no_key_gives_a_clear_message_and_makes_no_call(self):
        os.environ.pop('ANTHROPIC_API_KEY')
        c = fx.FakeClient([])
        with self.assertRaises(ai.ExtractError) as cm:
            self.run_extract(c)
        self.assertIn('No API key', str(cm.exception))
        self.assertIn('by hand', str(cm.exception))
        self.assertEqual(ai.key_source(), '')

    def test_env_wins_and_file_is_private(self):
        self.assertEqual((ai.key_source(), ai.get_key()), ('env', KEY))
        os.environ.pop('ANTHROPIC_API_KEY')
        ai.save_key(KEY)
        self.assertEqual((ai.key_source(), ai.get_key()), ('file', KEY))
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(ai.key_path().stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(ai.key_path().parent.stat().st_mode), 0o700)
        self.assertTrue(str(ai.key_path()).startswith(str(self.d / 'home')))   # per user, not in the shared data folder
        self.assertTrue(ai.remove_key())
        self.assertEqual(ai.key_source(), '')

    def test_bad_keys_are_refused(self):
        for bad in ('', 'short', 'has space in it but long enough to pass length x'):
            with self.assertRaises(ValueError):
                ai.save_key(bad)
        for bad in ('', 'short'):
            self.assertFalse(ai.key_path().exists())

    def test_the_key_never_reaches_the_request_logs_errors_or_project(self):
        logs = []

        class H(logging.Handler):
            def emit(self, rec):
                logs.append(rec.getMessage())
        h = H()
        logging.getLogger().addHandler(h)
        old = logging.getLogger().level
        logging.getLogger().setLevel(logging.DEBUG)
        try:
            c = fx.FakeClient([Err(f'auth failed for key {KEY}', 400)])
            with self.assertRaises(ai.ExtractError) as cm:
                self.run_extract(c)
            self.assertNotIn('TOPSECRET', str(cm.exception))
            self.assertNotIn('TOPSECRET', json.dumps(c.requests[0]))
            c = fx.FakeClient([Err(f'weird {KEY}', 418)])
            with self.assertRaises(ai.ExtractError) as cm:
                self.run_extract(c)
            self.assertNotIn('TOPSECRET', str(cm.exception))
            self.store.save(self.p)
            self.assertNotIn('TOPSECRET', json.dumps(self.p.to_dict()))
            self.assertNotIn('TOPSECRET', ' '.join(logs))
        finally:
            logging.getLogger().removeHandler(h)
            logging.getLogger().setLevel(old)

    def test_scrub(self):
        self.assertNotIn('TOPSECRET', ai.scrub(f'x {KEY} y', KEY))
        self.assertNotIn('abcdefgh', ai.scrub('Bearer sk-ant-abcdefghijkl', ''))
        self.assertEqual(ai.scrub('plain text', KEY), 'plain text')

    def test_the_client_is_built_without_sdk_retries(self):
        import anthropic
        with mock.patch.object(anthropic, 'Anthropic') as m:
            ai.make_client(KEY)
        kw = m.call_args.kwargs
        self.assertEqual(kw['max_retries'], 0)
        self.assertEqual(kw['api_key'], KEY)

    def test_settings_validation(self):
        ai.save_settings(model=' m1 ', dpi=1000)
        s = ai.load_settings()
        self.assertEqual((s['model'], s['dpi']), ('m1', 300))
        self.assertNotIn('key', json.dumps(s).lower())


if __name__ == '__main__':
    unittest.main()
