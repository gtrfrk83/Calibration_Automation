"""Static manifest of the operator-prompt call sites in a source file: where, what kind, which title / text expressions.  Test / porting helper.

A prompt is recorded in ONE canonical form whether it is still a Tk call (`messagebox.askyesno(t, m)`, `filedialog.asksaveasfilename(...)`,
`ui.confirm_steps(self.root, ...)`, `report_dialog.ask_details(root, ...)`) or already a UiPort call (`port.ask_yes_no(t, m)`, `port.message('info', t, m)`,
`port.save_file(...)`, `port.operator_prompt(...)`).  So a port of a file must leave its manifest byte-identical: same prompts, same title / text expressions,
same order inside each function.  (`parent` arguments are not part of the manifest.)  Source is parsed with `ast`, never run.

    python tools/ui_callsites.py FILE...        prints the manifest as JSON
    tests/golden_ui/callsites.json              the recorded manifests (tests/test_ui_callsites.py compares)
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

# legacy Tk spellings -> canonical kind
LEGACY = {
    'showinfo': 'info', 'showwarning': 'warning', 'showerror': 'error', 'askyesno': 'ask_yes_no', 'askokcancel': 'ask_ok_cancel',
    'askretrycancel': 'ask_retry_cancel', 'askyesnocancel': 'ask_yes_no_cancel', 'askstring': 'ask_text', 'askfloat': 'ask_number',
    'askinteger': 'ask_number', 'askopenfilename': 'choose_file', 'asksaveasfilename': 'save_file', 'askdirectory': 'choose_dir',
    'confirm_steps': 'operator_prompt', 'ask_details': 'report_details', 'ask_reading': 'ask_reading', 'ask_readings': 'ask_readings',
    'ask_range': 'ask_range',
}
LEGACY_RECEIVERS = {'messagebox', 'mb', 'filedialog', 'fd', 'simpledialog', 'sd', 'ui', 'ui_theme', 'report_dialog', 'hh', 'handheld_dmm', 'tkMessageBox'}
# the legacy calls whose FIRST positional argument is the parent window
PARENT_FIRST = {'confirm_steps', 'ask_details', 'ask_reading', 'ask_readings', 'ask_range'}
# UiPort spellings (ui_port.py) -> canonical kind ('message' takes its kind as first argument)
PORT = {'ask_yes_no': 'ask_yes_no', 'ask_ok_cancel': 'ask_ok_cancel', 'ask_retry_cancel': 'ask_retry_cancel', 'ask_yes_no_cancel': 'ask_yes_no_cancel',
        'ask_text': 'ask_text', 'ask_number': 'ask_number', 'choose_file': 'choose_file', 'save_file': 'save_file', 'choose_dir': 'choose_dir',
        'operator_prompt': 'operator_prompt', 'report_details': 'report_details', 'ask_reading': 'ask_reading', 'ask_readings': 'ask_readings',
        'ask_range': 'ask_range'}
PORT_RECEIVERS = {'port', 'uip', 'ui_port'}
DROP_KW = {'parent'}


def _src(node):
    return ast.unparse(node)


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.stack, self.out = [], []

    def _scope(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scope

    def visit_Call(self, node):
        entry = self._entry(node)
        # arguments first (a prompt nested in an argument is evaluated before the outer call), then this call
        self.generic_visit(node)
        if entry:
            self.out.append(entry)

    def _entry(self, node):
        f = node.func
        if not isinstance(f, ast.Attribute):
            return None
        recv = f.value.id if isinstance(f.value, ast.Name) else None
        attr, args, kind = f.attr, list(node.args), None
        if recv in LEGACY_RECEIVERS and attr in LEGACY:
            kind = LEGACY[attr]
            if attr in PARENT_FIRST and args:
                args = args[1:]
        elif (recv in PORT_RECEIVERS or (isinstance(f.value, ast.Call) and _src(f.value).endswith('get_ui()'))) and (attr in PORT or attr == 'message'):
            if attr == 'message':
                if not args or not isinstance(args[0], ast.Constant):
                    return None
                kind, args = args[0].value, args[1:]
            else:
                kind = PORT[attr]
        if kind is None:
            return None
        kws = {k.arg: _src(k.value) for k in node.keywords if k.arg and k.arg not in DROP_KW}
        if kind in ('ask_text', 'ask_number') and 'initial' in kws:       # WP-G: the port's `initial=` is the manifest's Tk spelling `initialvalue=` (recorded before any port)
            kws['initialvalue'] = kws.pop('initial')
        return {'where': '.'.join(self.stack) or '<module>', 'kind': kind, 'args': [_src(a) for a in args], 'kw': dict(sorted(kws.items()))}


def manifest(path):
    tree = ast.parse(Path(path).read_text(encoding='utf-8'), filename=str(path))
    v = _Visitor()
    v.visit(tree)
    return v.out


def main(argv=None):
    out = {str(p): manifest(p) for p in (argv if argv is not None else sys.argv[1:])}
    print(json.dumps(out, indent=1, sort_keys=True, ensure_ascii=False))


if __name__ == '__main__':
    main()
