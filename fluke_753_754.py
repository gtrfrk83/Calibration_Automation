"""Fluke 753 / 754 Documenting Process Calibrator performance verification - manual-reading procedure on the shared handheld engine (handheld_dmm.App).

The unit under test is itself a calibrator, so a point goes one of two ways (the spec's step['direction'], the section titles say "(UUT input)" / "(UUT output)"):

  direction 'measure'   the UUT MEASURES.  The lab calibrator (Fluke 5522A, the manual's own; 5560A / 5520A also offered) SOURCES the value through the engine's normal path
                        (set, read back, compare, standby after the point) and the technician types the UUT display.
                        UNCERTAINTY: the calibrator's published specification, its 'output' sheet (the existing report_pdf.point_uncertainty / uncertainty_budget path).
  direction 'source'    the UUT SOURCES (its OUTPUT).  MANUAL ENTRY ONLY: the technician types the reading of the external measuring instrument (the manual: Fluke 8508A DMM,
                        Tektronix FCA3000 counter).  No instrument is driven, no meter driver is used, nothing is read automatically, and no calibrator output is set (step['applied'] is None).
                        UNCERTAINTY: the lab's measuring standard.  Its 'input'-direction sheet gives the standard uncertainty, against the laboratory's Measure CMC.  The owner picks
                        the standard PER POINT (right-click the point > "Uncertainty standard: ..."); the default is the Keysight 3458A.  The other offered standards are the Keysight
                        34461A and 34465A: a choice is listed only when its sheet is installed (specs/standards) and covers the point, so the list simply tolerates a missing sheet.
  HART (754 only)       a pass / fail question, no uncertainty.

Nothing else differs from the handheld engine: the hook-up prompts, function prompts, reset to defaults before the first point, PDF 'Calibration Data' report, demo mode, run queue and procedure
modifications are all the shared engine's.  The pieces of this module are the uncertainty rules above, the labels of the reading window, the per-point uncertainty-standard choice (saved with the
progress and named in the report) and the RTD / thermocouple sensor keys of the scope and the calibrator sheets.

    fluke_753_754.main('753')       # what Procedures/Fluke_753_Verification.py does ('754': Procedures/Fluke_754_Verification.py)
"""
from __future__ import annotations

import sys
from decimal import Decimal

import handheld_dmm
import virtualbench
from handheld_dmm import SYMBOL, describe
from ui_port import ui as port

SPEC = 'fluke_753_754_pv.json'
DEFAULT_UNC_STANDARD = '3458A'                       # the measuring standard a source point uses until the owner picks another
UNC_STANDARDS = ('3458A', '34461A', '34465A')       # the offered measuring standards (owner, 2026-10-26); a model whose sheet is not installed is not listed
SOURCE_KINDS = ('DCV', 'DCI', 'OHM', 'FREQ')         # the kinds a source point is measured as (the spec's step['uut']['kind'])
RTD_VARIANT = 'Pt 385, 100 Ohm'                      # the calibrator sheet's RTD function (5522A: 'Temperature [RTD, Pt 385, 100 Ohm]')


def is_source(p):
    """True for a point the UUT SOURCES (its output): manual entry of an external measuring instrument."""
    return p.get('direction') == 'source'


def is_rtd(p):
    return bool(p.get('rtd')) and not is_source(p)


def unc_direction(p):
    """Direction of the standard-sheet row that gives the point's uncertainty: a UUT OUTPUT point is measured by the multimeter standard (its 'input' row);
    a UUT input point is sourced by the calibrator (its 'output' row).  None for a point with no uncertainty (HART)."""
    if is_source(p):
        return 'input'
    return 'output' if p.get('applied') else None


def have_standard(model):
    """True when the sheet of `model` is installed (specs/standards loaded into lab_registry.sqlite3); never raises."""
    try:
        import specmanager as sm
        if sm.standard(model) is None:
            sm.seed()
        return sm.standard(model) is not None
    except Exception:
        return False


def source_request(p):
    """(kind, nominal, unit, frequency) the measuring standard reads at a source point (the value the UUT is set to output)."""
    u = p['uut']
    unit = {'DCV': 'V', 'DCI': 'A', 'OHM': 'ohm', 'FREQ': 'Hz'}[u['kind']]
    return ('OHM4' if u['kind'] == 'OHM' else u['kind']), float(u['value']), unit, (u.get('frequency') if u['kind'] == 'FREQ' else None)


def freq_budget(p, calibrator):
    """Budget of a frequency-MEASURE point (Table 7): the calibrator's own output frequency specification at the applied frequency, against the lab's Frequency
    CMC (uncertainty_budget.build('FREQ', ..., direction='output'))."""
    import uncertainty_budget as ub
    return ub.build('FREQ', float(handheld_dmm.unc_frequency(p)), 'Hz', standard=calibrator, direction='output')


def source_budget(p, standard):
    """uncertainty_budget.Budget of a UUT OUTPUT point for measuring standard `standard`: its 'input' sheet row, against the laboratory's Measure CMC.  None when it cannot be built."""
    import uncertainty_budget as ub
    kind, nominal, unit, freq = source_request(p)
    try:
        return ub.build(kind, nominal, unit, standard=standard, frequency=freq, direction='input', basis='measure')
    except Exception:
        return None


def rtd_budget(p, standard):
    """Budget of an RTD measure point: the calibrator's Pt 385 (100 ohm) simulation in degC (its 'output' sheet) against the scope's RTD line of the same sensor."""
    import uncertainty_budget as ub
    try:
        return ub.build('TEMP', p['rtd_celsius'], 'degC', standard=standard, direction='output', tc=p['rtd'], variant=RTD_VARIANT)
    except Exception:
        return None


class App(handheld_dmm.App):
    """handheld_dmm.App with the direction-aware uncertainty and the per-point measuring-standard choice."""

    # ------------------------------------------------------------------ the measuring-standard choice (source points)
    def __init__(self, *a, **kw):
        self.unc_choice = {}                                      # {point id: measuring standard model} the owner picked; the default is DEFAULT_UNC_STANDARD
        self._unc_cache = {}
        super().__init__(*a, **kw)

    @staticmethod
    def unc_models():
        """The measuring standards offered for a source point whose sheet is installed (3458A first)."""
        return [m for m in UNC_STANDARDS if have_standard(m)]

    def unc_standard_of(self, p):
        """The measuring standard whose 'input' sheet gives source point p its uncertainty: the owner's pick, else the default."""
        m = self.unc_choice.get(str(p['id']))
        return m if m and m in self.unc_models() else DEFAULT_UNC_STANDARD         # a saved pick whose sheet is no longer installed falls back to the default

    def unc_options(self, p):
        """[model] of the installed measuring standards whose sheet covers source point p (a row of the 'input' direction at the value)."""
        out = []
        for m in self.unc_models():
            b = self._source_budget(p, m)
            if b is not None and b.hit is not None:
                out.append(m)
        return out

    def _source_budget(self, p, model):
        key = (str(p['id']), model)
        if key not in self._unc_cache:
            self._unc_cache[key] = source_budget(p, model)
        return self._unc_cache[key]

    def set_unc_choice(self, p, model):
        """Pick `model` ('' = the default) as the measuring standard of source point p's uncertainty; saved with the progress, named in the report."""
        old = self.unc_standard_of(p)
        if model and model != DEFAULT_UNC_STANDARD:
            self.unc_choice[str(p['id'])] = model
        else:
            self.unc_choice.pop(str(p['id']), None)
        new = self.unc_standard_of(p)
        self.status.set(f'Point {p["id"]}: the uncertainty is now that of the {new}' + (f' (was {old}).' if new != old else '.'))
        if self.asset.get().strip():
            self.save(silent=True)
        try:
            self.refresh()
        except Exception:
            pass

    def tree_menu_extras(self, pid):
        """Right-click entries on a source point: the measuring standard of its uncertainty (the existing per-point 'Uncertainty standard' choice)."""
        p = self.by_id.get(pid) or self.by_id.get(str(pid))
        if p is None or not is_source(p) or not self.has_uncertainty(p):
            return []
        if self.demo:
            return [('Uncertainty standard...', lambda: None, False, 'A demo run prints no uncertainty.')]
        options = self.unc_options(p)
        if not options:
            return [('Uncertainty standard...', lambda: None, False, 'No installed standard has an input-direction sheet row for this point, so it has no uncertainty.')]
        now = self.unc_standard_of(p)
        out = []
        for m in options:
            label = f'Uncertainty standard: {m}' + (' (default)' if m == DEFAULT_UNC_STANDARD else '') + ('  (selected)' if m == now else '')
            out.append((label, (lambda m=m: self.set_unc_choice(p, m)), True, ''))
        return out

    def save_fields(self):
        d = super().save_fields()
        if self.unc_choice:
            d['unc_choice'] = dict(self.unc_choice)             # recorded with the run: the measuring standard picked for a point's uncertainty
        return d

    def load_results(self, data):
        super().load_results(data)
        picked = data.get('unc_choice')
        self.unc_choice = {str(k): v for k, v in picked.items() if isinstance(v, str) and v} if isinstance(picked, dict) else {}

    # ------------------------------------------------------------------ the uncertainty of one point
    @staticmethod
    def has_uncertainty(p):
        """Points that should carry an uncertainty: the engine's rule for a UUT input point (a calibrator source), and for a UUT OUTPUT point a numeric reading of a
        DC volts / DC current / resistance / frequency standard (the measuring standard's input sheet).  HART: none."""
        if is_source(p):
            return p.get('test') == 'numeric' and not p.get('no_uncertainty') and (p.get('uut') or {}).get('kind') in SOURCE_KINDS
        return handheld_dmm.App.has_uncertainty(p)

    def _budget(self, p):
        """(Budget or None, standard model or None, direction) of point p."""
        if is_source(p):
            m = self.unc_standard_of(p)
            return self._source_budget(p, m), m, 'input'
        cal = self.calibrator_model()
        if self._freq_from_calibrator(p):
            return freq_budget(p, cal), cal, 'output'
        if is_rtd(p):
            return (rtd_budget(p, cal) if cal else None), cal, 'output'
        return None, cal, 'output'

    FREQ_FROM_CALIBRATOR = True         # per-procedure switch (owner rule 2026-10-26): a frequency-MEASURE point takes its uncertainty from the CALIBRATOR's own output frequency
                                        # specification (uncertainty_budget.build('FREQ', ..., calibrator model)), not the lab Frequency - Measure CMC alone.  False = the engine's old rule.

    def _freq_from_calibrator(self, p):
        return bool(self.FREQ_FROM_CALIBRATOR and not is_source(p) and p.get('test') == 'numeric' and p.get('unc_kind') == 'FREQ'
                    and not p.get('no_uncertainty') and self.calibrator_model())

    def _custom(self, p):
        return p.get('test') == 'numeric' and (is_source(p) or is_rtd(p) or self._freq_from_calibrator(p))

    def uncertainty_text(self, p):
        import uncertainty
        b, _m, _d = self._budget(p)
        if b is None or b.reported is None:
            if is_rtd(p):                                                          # no calibrator named (a hand-set point): the scope's RTD line alone
                try:
                    import uncertainty_budget as ub
                    b = ub.build('TEMP', p['rtd_celsius'], 'degC', tc=p['rtd'])
                except Exception:
                    return ''
                return uncertainty.format_value(b.reported, 'degC') if b.reported is not None else ''
            return ''
        return uncertainty.format_value(b.reported, b.unit)

    def certificate_row(self, p, r):
        if not self._custom(p):
            return super().certificate_row(p, r)
        import report_pdf
        row = super().certificate_row(dict(p, no_uncertainty=True), r)              # the engine's own row, with its own uncertainty step skipped
        row['Description'] = report_pdf.ascii_unit(row.get('Description', ''))
        row['Uncertainty'] = self.uncertainty_text(p) if self.has_uncertainty(p) else ''
        return row

    def certificate_fields(self, p):
        if not self._custom(p) or not self.has_uncertainty(p):
            return super().certificate_fields(p) if not is_source(p) else dict(TAR='', TUR='')
        try:
            import tartur
            b, _m, _d = self._budget(p)
            if b is None:
                return dict(TAR='', TUR='')
            factor = Decimal(str(p['factor']))
            low, high = float(Decimal(p['low']) * factor), float(Decimal(p['high']) * factor)
            tol = tartur.half_width(low, high)
            acc = (b.hit.limit, b.hit.row['unit']) if b.hit is not None else (None, None)
            res = tartur.from_values(tol, b.unit if not is_rtd(p) else 'degC', accuracy=acc[0], accuracy_unit=b.unit if acc[0] is not None else None,
                                     uncertainty=b.reported, uncertainty_unit=b.unit)
            return tartur.ratio_fields(res)
        except Exception:
            return dict(TAR='', TUR='')

    # ------------------------------------------------------------------ the instrument reference pictures
    @staticmethod
    def panel_pictures():
        """The owner's photos of the 753 / 754 (hookups.METERS['fluke753']['panels']): terminal close-up, then front view; the files that exist."""
        import hookups
        names = (hookups.METERS.get('fluke753') or {}).get('panels') or ()
        return [hookups.DIAGRAMS / n for n in names if (hookups.DIAGRAMS / n).is_file()]

    def _drawn_image(self, p, image):
        """The group's drawn hook-up picture (diagrams/hook_fluke753_<GROUP>.png); when that file is missing the owner's terminal photo is shown instead (then the front photo)."""
        if image is not None and getattr(image, 'is_file', lambda: False)():
            return image
        pics = self.panel_pictures()
        return pics[0] if pics else image

    # ------------------------------------------------------------------ the windows' words
    def reading_labels(self, p):
        if is_source(p):
            return dict(device='EXTERNAL MEASURING INSTRUMENT', source='UUT OUTPUT (source)')
        return dict(device='UUT DISPLAY', source='CALIBRATOR OUTPUT')

    def temperature_note(self):
        return ''                                                                   # the thermocouple wording of the shared note is the Type K simulation of the 80AK series; ours is in source_note

    def source_note(self):
        note = super().source_note()
        used = {}
        for p in self.points:
            if is_source(p) and self.has_uncertainty(p) and (str(p['id']) in self.found or str(p['id']) in self.left):
                used[self.unc_standard_of(p)] = used.get(self.unc_standard_of(p), 0) + 1
        if used:
            note = ' '.join(x for x in (note, 'UUT output points (read on an external instrument and typed in): the uncertainty is that of the measuring standard named here, its input-direction '
                                               'specification divided by its coverage divisor, with the laboratory Measure CMC as the floor: ' +
                                               ', '.join(f'{m} ({n} point(s))' for m, n in sorted(used.items())) + '.') if x)
        return note


def main(model, argv=None, spec=SPEC):
    """spec: a spec file name inside specs/ (or a path)."""
    argv = sys.argv if argv is None else argv

    def build(root):
        demo, fast = virtualbench.flags(argv)
        App(root, model, demo=demo, spec=handheld_dmm.load_spec(spec), fast_demo=fast)
    port.run_app(build)
