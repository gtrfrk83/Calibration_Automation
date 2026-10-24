"""Run queue: the review window is shown once per meter, in sequence, and each meter's PDF / report snapshot carries its own review.

The real handheld App with a run queue on the simulated calibrator (tests/test_beta_run_queue.EngineBase); only the Tk window class is replaced by a
scripted one.  Sorts after test_beta on purpose (tkinter stub).  Run:  python -m unittest tests.test_reprint_review_queue
"""
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

import test_beta_run_queue as Q  # noqa: E402


def setUpModule():
    Q.setUpModule()


class FakeWindow:
    made = []

    def __init__(self, parent, model, procedure='', demo=False, details=None, position=(1, 1)):
        self.model, self.position, self.prior = model, position, details
        FakeWindow.made.append(self)

    def run(self):
        import report_pdf
        m = self.model
        free = [(i, [k for k in m.options(i) if k != r.spec.default_std]) for i, r in enumerate(m.rows) if not r.spec.locked and len(m.options(i)) > 1]
        if self.position[0] == 1 and free:                         # only the first meter's operator changes a standard
            m.set_standard(free[0][0], free[0][1][0])
        d = dict(technician='T', temperature='23', humidity='45', standards=[], procedure=self.model.procedure, show_tar=False, show_tur=True)
        d['show_tar_tur'] = report_pdf.TarTur(False, True)
        return d


class ReviewQueue(Q.EngineBase):
    def setUp(self):
        super().setUp()
        tag = uuid.uuid4().hex[:6]
        self.A = tuple(f'{tag}-{n}' for n in (1, 2, 3))
        FakeWindow.made = []

    def test_one_review_per_meter_and_per_meter_records(self):
        import report_dialog
        import report_review
        import report_snapshot as rs
        import labregistry
        app = self.real(assets=self.A)
        self.hn.run_all()
        out = tempfile.mkdtemp()
        with mock.patch.object(report_review, 'ReviewWindow', FakeWindow), mock.patch.object(Q.h.filedialog, 'askdirectory', lambda **k: out, create=True):
            written = app.queue_export_pdfs()
        self.assertEqual(len(written), 3)
        self.assertEqual([w.position for w in FakeWindow.made], [(1, 3), (2, 3), (3, 3)])
        self.assertEqual([w.model.asset for w in FakeWindow.made], list(self.A))
        self.assertIsNone(app.__dict__.get('_review_all_meters'), 'the flag is cleared after the dialog')
        for n, asset in enumerate(self.A):
            run = labregistry.runs_for(asset)[0]
            snap = rs.load(run['id'])
            self.assertEqual(snap.status, rs.OK)
            rev = snap.data['details']['uncertainty_review']['reviews']
            self.assertEqual([r['asset'] for r in rev], list(self.A), 'the block lists every meter; each report applies its own by Instrument ID')
            mine = next(r for r in rev if r['asset'] == asset)
            self.assertEqual(mine['changed'], 1 if n == 0 else 0)
            if n == 0:
                ch = mine['changes'][0]
                self.assertEqual(snap.data['rows'][ch['idx']]['Uncertainty'], ch['uncertainty'])
                self.assertEqual(ch['original_standard'] != ch['standard'], True)

    def test_single_meter_report_of_a_queue_run_shows_one_review(self):
        import report_dialog
        import report_review
        app = self.real(assets=self.A)
        self.hn.run_all()
        with mock.patch.object(report_review, 'ReviewWindow', FakeWindow):
            d = report_dialog.ask_details(app.root, 'x')                  # the ordinary single-report path: no all-meters flag
        self.assertEqual(len(FakeWindow.made), 1)
        self.assertEqual(len(d['uncertainty_review']['reviews']), 1)


if __name__ == '__main__':
    unittest.main()
