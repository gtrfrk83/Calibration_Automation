"""Manual override of a reading, for a two-way procedure (the meter is read back automatically, the technician may type the reading instead).

Owner request (Fluke 8808A only, for now): 'a way to manually override a reading where the user can manually enter a reading in case it's needed ...
no need to annotate it on the report.'  Everything here is generic so another two-way procedure can adopt it; it is switched ON per App with
`MANUAL_OVERRIDE = True` and does nothing otherwise.

What it does
  * `parse_reading(p, text)`   a typed reading -> `Entered` (text padded to the point's resolution by handheld_dmm.pad_reading, the value in BASE
                               units, the display unit).  Same rules as the handheld manual entry: the number as the meter shows it, without the unit;
                               not a number / NaN / inf / overload text is rejected.  Display-only SI scaling: the typed number is in the unit the
                               meter shows for the point's range (200 mV range -> mV), the stored value stays in base units.
  * `ManualOverrideMixin`      the App side: an 'Enter reading manually' action button, a right-click entry on the point list, the dialog, a short
                               confirmation ('Use 1.0003 V as the reading for point N?'), the command-log line and the recording.
  * Pass / fail is NOT decided here: the App's own `_record` judges the typed value with the procedure's own limit logic.

Where the override is visible
  * The COMMAND LOG: 'MANUAL OVERRIDE point N: auto reading X (or none), entered Y'.  Never a password (there is none in this path).
  * The progress (checkpoint) file keeps `overridden` and `auto_reading` on the point's record.  Nothing reads them for the report: the PDF is built from
    reading + result only, so a report with an override is identical to one without (tests/test_8808a_manual_override.py compares the rows and the PDF text).
  * Demo mode: the value is recorded as synthetic like every demo result and nothing is written to the shared command log.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import ui_theme_core as ui                     # toolkit-free helpers only (si, si_row, si_scale); the entry window is manual_override_view_tk.py
from drivers.base import InstrumentError, SafetyError
from ui_port import ui as port

NOT_A_NUMBER = 'Enter the number exactly as the meter shows it, without the unit.'
OVERLOAD_LIMIT = 1.0e9          # the same overload threshold as the 8808A driver (Format 1, +/-1.0E+9): the automatic reading refuses it, so does a typed one


class ReadingUnavailable(InstrumentError):
    """The automatic reading of a point failed (timeout, unreadable, overload). Same message as the error it wraps; the App offers a typed reading.
    (The 8808A and 5491B engines have their own class of the same name and meaning; any InstrumentError subclass with this name is handled alike.)"""


def guard_read(read, *args, **kwargs):
    """read(*args) -> the reading; a failure is re-raised as ReadingUnavailable with the same text (a SafetyError and the operator's Stop at a surprise dialog
    are not readings that failed: they pass through unchanged)."""
    try:
        return read(*args, **kwargs)
    except SafetyError:
        raise
    except Exception as exc:
        if type(exc).__name__ in ('SurpriseStop', 'Stopped'):
            raise
        raise ReadingUnavailable(str(exc)) from exc


class ReadGuardMixin:
    """For an engine's IO class: `self._read()` is `self.dmm.read()` with a failure raised as ReadingUnavailable (the command sent is the same)."""

    def _read(self, *args):
        return guard_read(self.dmm.read, *args)


@dataclass(frozen=True)
class Entered:
    text: str           # the typed reading, filled out with zeros to the point's resolution (what the confirmation shows)
    value: float        # the same reading in BASE units (what is judged, stored and reported)
    unit: str           # display unit of `text` ('mV', 'V', 'kΩ' ...)

    @property
    def shown(self) -> str:
        return f'{self.text} {self.unit}'.strip()


def point_limits(p):
    """(low, high) of a point: its printed limits, or nominal -/+ error for the engines whose spec is a tolerance (display only: the engine's own judge decides)."""
    if p.get('low') is not None and p.get('high') is not None:
        return p['low'], p['high']
    if p.get('error') is not None and p.get('nominal') is not None:
        nom, err = Decimal(repr(float(p['nominal']))), Decimal(repr(abs(float(p['error']))))
        return float(nom - err), float(nom + err)
    low = p['low'] if p.get('low') is not None else (p.get('nominal') or 0)
    high = p['high'] if p.get('high') is not None else (p.get('nominal') or 0)
    return low, high


def entry_scale(p):
    """(limit_texts, unit_text, scale) of the unit a technician types in for point p: the unit the report and the on-screen table use for the point
    (ui.si_row of nominal and limits, the way report_pdf.cert_row scales them; display only). limit_texts are the low / high limits in that unit with just
    enough decimals (the point's resolution); scale is a Decimal (1e-3 for mV)."""
    nominal = p.get('nominal') or 0
    low, high = point_limits(p)
    ref = max(abs(float(low)), abs(float(high)), abs(float(nominal)))
    vals, _reads, unit = ui.si_row([nominal, low, high], p['unit'])
    scale, _unit = ui.si_scale(ref, p['unit'])
    return vals[1:3], unit, Decimal(repr(scale))


def parse_reading(p, text) -> Entered:
    """A typed reading -> Entered.  Raises ValueError (with the message to show) for anything that is not a plain finite number."""
    from handheld_dmm import pad_reading           # the one padding rule of every manual-entry procedure (NOTES.md Standing rules)
    raw = (text or '').strip()
    if not raw:
        raise ValueError(NOT_A_NUMBER)
    if raw.upper().replace('.', '') in ('OL', '0L', 'OVERLOAD'):
        raise ValueError('An overload cannot be entered here: type the number the meter shows, or stop the run and check the input, range and function.')
    try:
        number = Decimal(raw.replace(',', ''))
    except InvalidOperation:
        raise ValueError(NOT_A_NUMBER) from None
    if not number.is_finite():
        raise ValueError('Enter a number.')
    vals, unit, scale = entry_scale(p)
    padded = pad_reading({'low': vals[0], 'high': vals[1]}, raw)
    base = Decimal(padded.replace(',', '')) * scale
    value = float(f'{float(base):.9g}')              # the same 9 significant digits judge_numeric stores
    if abs(value) >= OVERLOAD_LIMIT:
        raise ValueError('That is larger than the meter can read (overload).')
    return Entered(padded, value, unit)


def ascii_text(text: str) -> str:
    return str(text).replace('µ', 'u').replace('μ', 'u').replace('Ω', 'ohm')


def base_text(p, value) -> str:
    """A base-unit reading for the command log ('1.00031 V'), ASCII."""
    return f'{float(value):.9g} {ascii_text(p["unit"])}'.strip()


def log_text(p, entered: Entered, auto=None, why='', mode='') -> str:
    """'MANUAL OVERRIDE point N: auto reading X (or none), entered Y' - the command-log line (ASCII, no secrets)."""
    auto_t = 'none' + (f' ({why})' if why else '') if auto is None else base_text(p, auto)
    return (f'MANUAL OVERRIDE point {p["id"]}: auto reading {auto_t}, entered {ascii_text(entered.shown)} = {base_text(p, entered.value)}'
            + (f' [{mode}]' if mode else ''))


# ============================================================================ the dialog
def ask_manual_reading(parent, p, total, auto=None, reason='', cancel_text='Cancel', demo=False, stored=None):
    """Modal entry window.  Returns Entered, or None when cancelled / stopped.  The short confirmation is asked here, after the typed value is valid,
    so a wrong click costs one answer; an invalid entry shows its message in the window and stays open.
    The window itself is the toolkit's (manual_override_view_tk.ask_reading_window); what the Use button does with the typed text is `done` below."""
    vals, unit, _scale = entry_scale(p)

    def done(win, typed, clear_error):
        """The Use button: ('error', message) for a text that is not a reading (the window stays open, message shown), ('again', None) when the operator
        declined the confirmation (the window stays open), ('use', Entered) when confirmed."""
        try:
            entered = parse_reading(p, typed)
        except ValueError as exc:
            return 'error', str(exc)
        clear_error()
        if not port.ask_yes_no('Use this reading?', f'Use {entered.shown} as the reading for point {p["id"]}?', parent=win):
            return 'again', None
        return 'use', entered
    return port.view('manual_override_view').ask_reading_window(parent, p, total, vals, unit, reason, cancel_text, demo, stored, done)


# ============================================================================ the App side
class ManualOverrideMixin:
    """Add to an App class (after the engine's own mixins) and set MANUAL_OVERRIDE = True.  The App provides: root, status (StringVar), tree, results,
    io (None when not connected), demo, busy, asset, is_manual(p), _record(p, reading, synthetic, manual, extra=None), confirm_found_overwrite([p])
    and the two hooks `mo_point(iid)` (the point of a list row) and `mo_total()` (points in the procedure).  Its run loop sets `_mo_current` while a point is measured and calls `mo_take_pending(p)` when the
    automatic reading arrives, and `mo_failed(p, exc)` when the automatic reading failed."""
    MANUAL_OVERRIDE = False
    _mo_current = None          # the point being measured right now (set by the run loop)
    _mo_pending = None          # (point id, Entered) typed while that point was being measured: replaces its automatic reading
    mo_events = ()              # what was logged (kept in memory too, for demo mode where there is no command log)

    # ---- hooks the App may override ---------------------------------------------------------------------------------------------
    def mo_point(self, iid):
        raise NotImplementedError

    def mo_total(self) -> int:
        raise NotImplementedError

    def is_manual(self, p):
        """Points measured with a standard the technician connects (flag stored on the record); an engine that has the idea overrides this."""
        return False

    def mo_applicable(self, p):
        """(typing allowed, why not) for point p: False for a point whose result is not a number the technician reads (a pass / fail self-test ...)."""
        return True, ''

    def mo_record(self, p, value, synthetic, extra):
        """Record the typed value through the App's own _record (its limit logic judges it).  An engine whose _record has another shape overrides this."""
        import inspect
        kwargs = dict(extra=extra)
        try:
            if 'manual' in inspect.signature(self._record).parameters:
                kwargs['manual'] = self.is_manual(p)
        except (TypeError, ValueError):
            pass
        self._record(p, value, synthetic, **kwargs)

    def mo_begin(self, p):
        """The run loop calls this when point p starts to be measured."""
        self._mo_current = p

    def mo_end(self):
        self._mo_current = None

    def mo_reset_run(self):
        self._mo_pending = None
        self._mo_current = None

    def mo_finish(self, p, reading, synthetic, record):
        """The automatic reading of p arrived: the typed one armed during the measurement replaces it (logged as the auto reading), else record(reading) as always."""
        typed = self.mo_take_pending(p)
        self._mo_current = None
        if typed is not None:
            self.mo_commit(p, typed, auto=reading)
        else:
            record()

    def mo_recover(self, p, exc) -> bool:
        """The automatic reading failed: True when a typed reading was committed (the run goes on), False = stop the run as before."""
        typed = self.mo_failed(p, exc)
        self._mo_current = None
        if typed is None:
            return False
        self.mo_commit(p, typed, auto=None, why=str(exc))
        return True

    def mo_standby(self):
        """Outputs to standby / off (the standing rule) after a typed reading replaced a point: the engine's IO method."""
        self.io.standby()

    # ---- engines whose points run on one worker thread (the oscilloscopes): the same rules, the dialog is asked on the UI thread ------------------------------
    @staticmethod
    def mo_failed_reading(exc) -> bool:
        """An instrument error of a point (not a safety stop, not the operator's Stop at a surprise dialog, not a Skip) that a typed reading may replace."""
        return isinstance(exc, InstrumentError) and not isinstance(exc, SafetyError) and type(exc).__name__ != 'SurpriseStop'

    def mo_worker_point(self, p, run):
        """Worker thread: run() -> (reading, raw).  Returns (reading, raw) to be recorded as always, or None when a typed reading was recorded in its place
        (armed while the point was measured, or typed after the automatic reading failed); a failure nobody types a reading for is re-raised unchanged."""
        import app_settings
        self.mo_begin(p)
        try:
            try:
                reading, raw = run()
            except Exception as exc:
                if not (self.mo_failed_reading(exc) and app_settings.manual_override_on()):
                    raise
                typed = self.mo_take_pending(p) or self.request('mo_ask', dict(p=p, reason=str(exc), cancel='Stop run'))
                if typed is None:
                    raise
                self.mo_commit(p, typed, auto=None, why=str(exc))
                return None
            typed = self.mo_take_pending(p)
            if typed is not None:
                self.mo_commit(p, typed, auto=reading)
                return None
            return reading, raw
        finally:
            self._mo_current = None

    def mo_mode_label(self) -> str:
        return getattr(self, 'mode_label', '')

    # ---- UI wiring --------------------------------------------------------------------------------------------------------------
    def mo_add_button(self, shell):
        """The 'Enter reading manually' action button (no button when the override is off)."""
        if not self.MANUAL_OVERRIDE:
            return None
        self.btn_manual = shell.add_action('Enter reading manually', self.mo_button_clicked, short='Manual')
        return self.btn_manual

    def tree_menu_extras(self, pid):
        """Entries for the point list's right-click menu (procmods_point_ui.attach_tree_menu): [(label, command, enabled, why)]."""
        if not self.MANUAL_OVERRIDE:
            return []
        p = self.mo_point(pid)
        ok, why = self.mo_state(p)
        import app_settings
        if not app_settings.manual_override_on():                   # File > Settings
            ok, why = False, app_settings.OFF_TEXT
        return [('Enter reading manually...', lambda: self.mo_enter_for(p), ok, why)]

    def pm_bind_tree(self, tree, resolver=None):
        """Only reached by an App without the procedure-modification layer (ProcModsMixin has its own, which also shows these entries): the point list's right-click menu
        holds 'Enter reading manually...'."""
        if not self.MANUAL_OVERRIDE:
            return
        try:
            port.view('manual_override_view').attach_tree_menu(self, tree, resolver)
        except Exception:
            pass

    def mo_state(self, p):
        """(enabled, why not) for point p right now."""
        ok, why = self.mo_applicable(p)
        if not ok:
            return False, why
        if self.busy:
            if self._mo_current is not None and self._mo_current['id'] == p['id']:
                return True, ''
            return False, 'A run is in progress: only the point being measured can be entered.'
        return True, ''

    def mo_button_clicked(self):
        if self.busy:
            p = self._mo_current
            if p is None:
                port.message('info', 'Enter reading manually', 'No point is being measured at this moment.', parent=self.root)
                return
        else:
            sel = self.tree.selection()
            if not sel:
                port.message('info', 'Enter reading manually', 'Select a test point first.', parent=self.root)
                return
            p = self.mo_point(sel[0])
        self.mo_enter_for(p)

    def mo_enter_for(self, p):
        import app_settings
        ok, why = self.mo_state(p)
        if not app_settings.manual_override_on():                   # File > Settings
            ok, why = False, app_settings.OFF_TEXT
        if not ok:
            port.message('info', 'Enter reading manually', why, parent=self.root)
            return
        if self.busy:
            self.mo_arm(p)
        else:
            self.mo_replace(p)

    # ---- while the point is being measured --------------------------------------------------------------------------------------
    def mo_arm(self, p):
        """Typed while point p is measured: the automatic reading is replaced by this one when it arrives (it is logged as the auto reading)."""
        entered = self.mo_ask(p, cancel_text='Cancel')
        if entered is None:
            return
        if self._mo_current is None or self._mo_current['id'] != p['id']:       # the point finished while the window was open
            port.message('info', 'Enter reading manually', f'Point {p["id"]} has just been recorded. Select it and use Enter reading manually to replace its result.', parent=self.root)
            return
        self._mo_pending = (p['id'], entered)
        self.status.set(f'Point {p["id"]}: {entered.shown} will be used as the reading instead of the automatic one.')

    def mo_take_pending(self, p):
        """Called by the run loop when point p's automatic reading (or its failure) arrives: the armed Entered, once, else None."""
        pending, self._mo_pending = self._mo_pending, None
        if pending is not None and pending[0] == p['id']:
            return pending[1]
        return None

    def mo_failed(self, p, exc):
        """The automatic reading failed: the typed one (armed earlier, or asked for now) or None = stop the run as before."""
        import app_settings
        if not app_settings.manual_override_on():            # File > Settings: no typed replacement is offered, the run stops as it always did
            return None
        armed = self.mo_take_pending(p)
        if armed is not None:
            return armed
        return self.mo_ask(p, reason=str(exc), cancel_text='Stop run')

    # ---- a point that is already stored (or not yet measured), run idle ----------------------------------------------------------
    def mo_replace(self, p):
        if not self.asset.get().strip():
            port.message('warning', 'Instrument ID', 'Enter an instrument ID.', parent=self.root)
            return
        if not self.confirm_found_overwrite([p]):
            return
        key = str(p['id'])
        old = self.results.get(key) or {}
        stored = ''
        if old.get('reading') is not None:
            stored = ui.si(old['reading'], p['unit']) if hasattr(ui, 'si') else str(old['reading'])
        entered = self.mo_ask(p, stored=stored)
        if entered is None:
            return
        auto = old.get('auto_reading') if old.get('overridden') else old.get('reading')       # the reading the instrument gave, not an earlier typed one
        self.mo_commit(p, entered, auto, why='' if old else 'point not measured', idle=True)
        self.status.set(f'Point {p["id"]}: reading {entered.shown} entered by hand.')

    # ---- the dialog and the recording -------------------------------------------------------------------------------------------
    def mo_ask(self, p, reason='', cancel_text='Cancel', stored=''):
        return ask_manual_reading(self.root, p, self.mo_total(), reason=reason, cancel_text=cancel_text, demo=self.demo, stored=stored)

    def mo_log(self, text):
        """The command-log line.  Connected: the session's CommandLog, saved to disk now.  Not connected: a one-line log appended to the shared file.
        Demo: kept in memory only (a demo never writes evidence)."""
        self.mo_events = tuple(self.mo_events) + (text,)
        if self.demo:
            return
        io = getattr(self, 'io', None)
        try:
            if io is not None:
                io.log.add('--', text, 'OPERATOR')
                io.save_log()
            else:
                import drivers
                log = drivers.CommandLog()
                log.add('--', text, 'OPERATOR')
                log.append_default(f'Fluke manual override ({self.asset.get().strip() or "no asset"})')
        except Exception:
            pass                                      # a log problem never loses the reading

    def mo_commit(self, p, entered: Entered, auto=None, why='', idle=False):
        """Log, then record the typed value through the App's own _record (which judges it with the procedure's own limit logic)."""
        mode = (self.mo_mode_label() + (', demo' if self.demo else '')).strip(', ')
        self.mo_log(log_text(p, entered, auto, why, mode))
        if idle and getattr(self, 'io', None) is not None:
            try:
                self.mo_standby()                      # nothing was output, but the standing rule is 'standby after every point': make sure
            except Exception:
                pass
        self.mo_record(p, entered.value, bool(self.demo), dict(overridden=True, auto_reading=auto))
