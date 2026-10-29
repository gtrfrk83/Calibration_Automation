"""A datasheet frequency / period point whose level is in Vpp is sourced as a SQUARE wave of that peak-to-peak amplitude (5522A / 5560A WAVE SQUARE), then the
calibrator goes back to a sine at standby.  Points without Vpp are untouched (sine)."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
h = make_io = SPEC = PTS = None


def setUpModule():
    global h, make_io, SPEC, PTS
    import _tk_stub
    _tk_stub.install()
    import handheld_dmm as _h
    from tests.test_handheld_options import make_io as _make_io
    h, make_io = _h, _make_io
    SPEC = h.load_spec('fluke_80_series_v_pv.json')
    PTS = {p['id']: p for p in h.points_for(SPEC, '87V')}


def acv_point():
    p = next(p for p in PTS.values() if p.get('kind') == 'ACV' and p.get('applied') and p['applied'].get('frequency'))
    return copy.deepcopy(p)


class SquareLevelTests(unittest.TestCase):
    def test_a_vpp_level_makes_a_square_wave_and_standby_restores_the_sine(self):
        io, t = make_io(SPEC)
        p = acv_point()
        p['applied'] = dict(value=1.0, frequency=1000.0, waveform='square')
        p['settle'] = 0
        io.apply(p)
        self.assertEqual(t.bench.fluke['wave'], 'SQUARE')
        self.assertIn('WAVE SQUARE; OUT 1V,1000Hz; DC_OFFSET 0V', ' '.join(t.sent).replace('1kHz', '1000Hz'))
        self.assertIn('p-p square wave', h.output_text(p))
        io.standby()
        self.assertEqual(t.bench.fluke['wave'], 'SINE')
        self.assertFalse(io.cal.wave_nonsine)

    def test_without_vpp_the_point_stays_a_sine(self):
        io, t = make_io(SPEC)
        p = acv_point()
        p['settle'] = 0
        io.apply(p)
        self.assertEqual(t.bench.fluke['wave'], 'SINE')
        self.assertNotIn('p-p square', h.output_text(p))

    def test_a_calibrator_without_square_refuses_instead_of_sourcing_a_sine(self):
        io, t = make_io(SPEC)
        p = acv_point()
        p['applied'] = dict(value=1.0, frequency=1000.0, waveform='square')
        p['settle'] = 0
        io.cal = type('NoSquare', (), {'label': 'Test cal', 'standby_quiet': lambda s: None, 'wave_nonsine': False})()
        with self.assertRaises(Exception) as cm:
            io.apply(p)
        self.assertIn('cannot make a square wave', str(cm.exception))

    def test_the_exported_spec_marks_the_applied_level_only_for_square_points(self):
        import datasheet_builder as db
        import datasheet_builder_specs as dsp
        import dsb_fixtures as fx
        ds = fx.dmm_34461a_like()
        fq = next(f for f in ds.functions if f.kind == 'FREQ')
        pts = list(fq.points)
        self.assertTrue(pts)
        pts[0].settings['waveform'] = 'square'
        res = dsp.export_spec(ds)
        self.assertIsNotNone(res.spec, [str(x) for x in res.problems])
        freq_steps = [st for st in res.spec['steps'] if st['dsb']['kind'] == 'FREQ']
        marked = [st['id'] for st in freq_steps if st['applied'].get('waveform') == 'square']
        self.assertEqual(marked, [pts[0].id])


if __name__ == '__main__':
    unittest.main()
