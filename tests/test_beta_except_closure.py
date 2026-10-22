"""Guard: no closure may capture an `except ... as NAME` variable.

Python 3 deletes NAME when the except block ends, so a lambda / nested function
defined inside the block that reads NAME and runs later (root.after, a thread
target, a callback) raises NameError.  Bind it first and capture by default arg:
    err = exc
    self.root.after(0, lambda err=err: self._error(err))
"""
import ast, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {'tests', '.claude', '.git', '__pycache__'}


def repo_py_files(root=ROOT):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in fns:
            if fn.endswith('.py'):
                yield os.path.join(dp, fn)


def _loads(nodes, name):
    for n in nodes:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Load):
                return sub.lineno
    return None


def _param_names(a):
    out = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    if a.vararg: out.add(a.vararg.arg)
    if a.kwarg: out.add(a.kwarg.arg)
    return out


def find_violations(source, filename='<src>'):
    """[(line, name)] for closures inside an except-as block that read the name."""
    tree = ast.parse(source, filename)
    bad = []
    for h in ast.walk(tree):
        if not isinstance(h, ast.ExceptHandler) or not h.name:
            continue
        name = h.name
        for stmt in h.body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Lambda):
                    if name in _param_names(node.args):
                        continue
                    ln = _loads([node.body], name)      # defaults are evaluated at once: allowed
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if name in _param_names(node.args):
                        continue
                    ln = _loads(node.body, name)
                else:
                    continue
                if ln is not None:
                    bad.append((ln, name))
    return sorted(set(bad))


class ExceptClosureScan(unittest.TestCase):
    def test_detector_catches_the_known_bug(self):
        src = ("def f(self):\n  try:\n    pass\n  except Exception as exc:\n"
               "    self.root.after(0, lambda: self._error(exc))\n")
        self.assertEqual(find_violations(src), [(5, 'exc')])
        src2 = ("try:\n  pass\nexcept Exception as e:\n  def cb():\n    print(e)\n  go(cb)\n")
        self.assertEqual(find_violations(src2), [(5, 'e')])

    def test_detector_allows_safe_forms(self):
        src = ("try:\n  pass\nexcept Exception as exc:\n  err = exc\n"
               "  after(0, lambda err=err: show(err))\n  after(0, lambda e=exc: show(e))\n"
               "  msg = str(exc)\n")
        self.assertEqual(find_violations(src), [])

    def test_repo_has_no_except_variable_closures(self):
        found = []
        for path in repo_py_files():
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
            for ln, name in find_violations(src, path):
                found.append(f'{os.path.relpath(path, ROOT)}:{ln} uses {name!r} inside a closure')
        self.assertEqual(found, [], 'closure reads an except-as variable that is deleted when the block ends:\n' + '\n'.join(found))


if __name__ == '__main__':
    unittest.main()
