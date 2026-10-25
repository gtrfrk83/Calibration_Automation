"""Reset every instrument to its default settings before the first test point of a run (Stage 7 rule).

One shared helper used by every engine and procedure at the start of EVERY run (a first run, a re-run, and a resume after Stop):

    report = reset_startup.reset_all(standards, uuts, confirm=ask, log=command_log)

  * standards: the reference instruments (calibrators, 5790B, counters ...); uuts: the instruments under test that are remote-controlled.
    Both are drivers.Instrument objects that are already open. A unit under test with no software reset (RESET_EXEMPT) is not touched.
  * Resetting a unit under test can erase settings stored on it, so before any instrument is touched a notice is shown through
    `confirm(text) -> bool`. Declining raises ResetDeclined and nothing has been sent. confirm=None means "already accepted" (the engines'
    UI code asks first on the UI thread, then runs the reset on the worker thread; simulated-bench tests pass confirm=None or a stub).
  * Each instrument runs Instrument.reset_to_defaults(): the reset command (locked, never overridable), *CLS, wait, error queue, then its
    own known-state / outputs-off steps. A reset write is never retried. The first failed step stops everything: every instrument is
    put to standby / off (cleanup) and ResetFailed is raised, so the run ends BEFORE any test point.
  * Success is recorded in the command log as 'Instruments reset to default settings at start: <names>'.
  * Opt-in exception (Fluke 8808A, at the owner's request): an App that sets AppResetMixin.RESET_ONCE_PER_SESSION = True resets on the FIRST Run of a
    session only (a session = one connection of that window); later Runs log 'reset skipped: already reset this session' and call reset_skip_run().

Demo mode never calls this (there are no instruments) and writes nothing that could look like evidence.
"""
from __future__ import annotations

from ui_port import ui as port                 # thread hand-offs (post) and the reset dialogs go through the UI port (ui_port.py)

LOG_LINE = 'Instruments reset to default settings at start'


class ResetDeclined(RuntimeError):
    """The operator declined the unit-under-test notice. No instrument was touched."""


class ResetFailed(RuntimeError):
    """A reset step failed. `report` is the StartupReport; outputs were sent to standby / off; the run must not start."""

    def __init__(self, report):
        self.report = report
        super().__init__(report.failure_text())


class StartupReport:
    def __init__(self):
        self.reports = []                # [ResetReport] in the order run
        self.ok = True
        self.safe_state = []             # [(label, ok)] outputs-off attempts after a failure

    @property
    def names(self):
        return [r.instrument for r in self.reports if not r.exempt]

    @property
    def exempt(self):
        return [r for r in self.reports if r.exempt]

    def text(self) -> str:
        return '\n'.join(r.text() for r in self.reports)

    def failure_text(self) -> str:
        bad = next((r for r in self.reports if not r.ok), None)
        if bad is None:
            return 'reset failed'
        step = bad.failed_step
        extra = ''.join(f'\n  {lbl}: {"standby / off sent" if ok else "COULD NOT CONFIRM - check the front panel"}' for lbl, ok in self.safe_state)
        return (f'{bad.instrument} did not reset to its default settings ({step.name if step else "?"}: {step.detail if step else ""}). '
                f'The run was not started.{extra}')


def uut_notice(uuts) -> str | None:
    """The text of the unit-under-test notice, or None when no UUT will be reset (none given, or all exempt)."""
    names = [u.label for u in uuts if not getattr(u, 'RESET_EXEMPT', '')]
    if not names:
        return None
    return ('Before the first test point every instrument is reset to its default settings.\n\n'
            f'Unit under test that will be reset: {", ".join(names)}.\n\n'
            'Resetting a unit under test can ERASE settings stored on it (set-ups, configuration, preferences). '
            'Save anything you need from it first.\n\nReset the instruments and start?')


def _safe_state(instruments, rep):
    """Best effort after a failure: outputs to standby / off. cleanup() never raises."""
    for inst in instruments:
        try:
            inst.cleanup()
            ok = getattr(inst, 'standby_confirmed', getattr(inst, 'output_off_confirmed', True))
            rep.safe_state.append((inst.label, bool(ok)))
        except Exception:
            rep.safe_state.append((inst.label, False))


def reset_all(standards, uuts=(), *, confirm=None, log=None) -> StartupReport:
    """See the module docstring. Raises ResetDeclined (nothing touched) or ResetFailed (outputs standby / off)."""
    standards, uuts = [s for s in standards if s is not None], [u for u in uuts if u is not None]
    notice = uut_notice(uuts)
    if notice and confirm is not None and not confirm(notice):
        raise ResetDeclined('The reset of the unit under test was declined; the run was not started and no instrument was touched.')
    rep = StartupReport()
    everything = standards + uuts
    for inst in everything:                       # sources first, then the unit under test
        r = inst.reset_to_defaults()
        rep.reports.append(r)
        if not r.ok:
            rep.ok = False
            _safe_state(everything, rep)
            if log is not None:
                log.add('!!', f'RESET FAILED, run not started: {r.instrument}', 'RESET')
            raise ResetFailed(rep)
    if log is not None:
        line = f'{LOG_LINE}: {", ".join(rep.names)}' if rep.names else 'No software reset was needed at start (every instrument is exempt or manual)'
        if rep.exempt:
            line += '; exempt (no software reset): ' + ', '.join(r.instrument for r in rep.exempt)
        log.add('--', line, 'RESET')
    return rep


class IOResetMixin:
    """For the engines' IO classes: define reset_roles() -> (standards, uuts); reset_at_start() runs the shared helper."""

    def reset_roles(self):
        raise NotImplementedError

    def reset_at_start(self, confirm=None) -> StartupReport:
        standards, uuts = self.reset_roles()
        return reset_all(standards, uuts, confirm=confirm, log=self.log)


class AppResetMixin:
    """For the Tk apps: reset_then(proceed) asks the notice on the UI thread, resets on a worker thread, then calls proceed() on the UI thread.
    Needs self.root, self.demo, self.io (with IOResetMixin, or None), self.status (tk variable) and self.busy. Declining or a failure ends the run
    (busy False) before any test point. Apps with an instrument outside the IO class (e.g. the handheld IR meter) override reset_extra_uuts()."""

    def reset_extra_uuts(self):
        return []

    def reset_roles(self):
        standards, uuts = self.io.reset_roles() if self.io is not None else ([], [])
        return list(standards), [u for u in list(uuts) + list(self.reset_extra_uuts()) if u is not None]

    def reset_log(self):
        return self.io.log if self.io is not None else None

    def reset_ask(self, text) -> bool:
        from ui_port import ui as port
        return port.ask_ok_cancel('Reset instruments', text, icon='warning')

    def reset_error(self, text):
        from ui_port import ui as port
        port.message('error', 'Reset failed - run not started', text)

    def reset_notice_ok(self) -> bool:
        """The unit-under-test notice on the UI thread (before any instrument is touched). False = declined: the run is ended."""
        notice = uut_notice(self.reset_roles()[1])
        if notice and not self.reset_ask(notice):
            self.busy = False
            self.status.set('Run cancelled: the instruments were not reset (nothing was touched).')
            return False
        return True

    def reset_run(self):
        """Worker-thread part: reset everything (the notice has been accepted already). Raises ResetFailed."""
        standards, uuts = self.reset_roles()
        return reset_all(standards, uuts, confirm=None, log=self.reset_log())

    # Opt-in, per App (default False = the Stage 7 rule: reset on EVERY run). True = the reset runs on the first Run of a session only (see SKIP_LINE).
    RESET_ONCE_PER_SESSION = False
    _reset_done_for = None          # the connection (self.io) that was reset successfully; a new connection is never equal to it

    def reset_done_this_session(self) -> bool:
        return bool(self.RESET_ONCE_PER_SESSION) and self.io is not None and self._reset_done_for is self.io

    def reset_forget(self, *_args):
        """The next Run resets again (a settings change, a failed skip check). Also usable as a Tk variable trace callback."""
        self._reset_done_for = None

    def reset_skip_run(self):
        """Worker-thread part of a Run whose reset is skipped: the safe parts (standby / off, connection, status). Apps that set RESET_ONCE_PER_SESSION override it."""
        raise NotImplementedError('an App with RESET_ONCE_PER_SESSION must define reset_skip_run()')

    def reset_then(self, proceed):
        import threading
        if getattr(self, 'fast_demo', self.demo):           # fast demo: no instruments, nothing to reset, nothing logged as evidence (a virtual bench resets its simulated instruments)
            proceed(); return
        if self.reset_done_this_session():
            return self._reset_skipped_then(proceed)
        if not self.reset_notice_ok():
            return
        self.status.set('Resetting instruments to default settings ...')
        io = self.io

        def work():
            try:
                self.reset_run()
                if self.RESET_ONCE_PER_SESSION:
                    self._reset_done_for = io                # only a SUCCESSFUL reset counts: a failed one leaves the next Run to reset again
                port.post(self.root, proceed)
            except Exception as exc:
                msg = str(exc)
                port.post(self.root, lambda: self._reset_failed(msg))
        threading.Thread(target=work, daemon=True).start()

    SKIP_LINE = 'reset skipped: already reset this session'

    def _reset_skipped_then(self, proceed):
        import threading
        log = self.reset_log()
        if log is not None:
            log.add('--', self.SKIP_LINE, 'RESET')
        self.status.set('Reset skipped: the instruments were already reset this session. Checking the connection and status ...')

        def work():
            try:
                self.reset_skip_run()
                port.post(self.root, proceed)
            except Exception as exc:
                msg = str(exc)
                self.reset_forget()                          # state unknown: the next Run resets again
                port.post(self.root, lambda: self._reset_failed(msg, skipped=True))
        threading.Thread(target=work, daemon=True).start()

    def _reset_failed(self, msg, skipped=False):
        self.busy = False
        if skipped:
            self.status.set('Connection / status check failed - run not started: ' + msg.splitlines()[0])
            self.reset_error('The reset was skipped (already reset this session) but the check before the run failed. The next Run resets the instruments again.\n\n' + msg)
            return
        self.status.set('Reset failed - run not started: ' + msg.splitlines()[0])
        self.reset_error(msg)


class SessionNotice:
    """Thread-safe confirm(text) for apps whose worker threads each run one test at a time (the WaveSurfer procedure): the unit-under-test
    notice is shown on the UI thread, the answer is remembered while tests keep starting (sliding `ttl` seconds), so a batch of points is
    asked once, not once per point. A decline (or no answer within `timeout`) returns False, which makes reset_all raise ResetDeclined."""

    def __init__(self, root, ask, ttl=600.0, timeout=600.0, clock=None):
        import time
        self.root, self.ask, self.ttl, self.timeout = root, ask, ttl, timeout
        self.clock = clock or time.monotonic
        self._ok_until = 0.0

    def __call__(self, text) -> bool:
        import threading
        now = self.clock()
        if now < self._ok_until:
            self._ok_until = now + self.ttl
            return True
        if threading.current_thread() is threading.main_thread():
            ok = bool(self.ask(text))
        else:
            box, done = [], threading.Event()

            def on_ui():
                try:
                    box.append(bool(self.ask(text)))
                finally:
                    done.set()
            port.post(self.root, on_ui)
            ok = done.wait(self.timeout) and bool(box and box[0])
        if ok:
            self._ok_until = self.clock() + self.ttl
        return ok
