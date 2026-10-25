"""Which procedures flip to 'Changed since verification' between two source trees (the method of NOTES.md 'Readiness check ... surprise-wiring').

    python tools/ui_flips.py BASE_TREE TREE

Every procedure with a sidecar is marked verified in a THROW-AWAY registry as installed in BASE_TREE (a clean checkout of the base commit, e.g. a `git worktree`);
then the status of each procedure is read with the registry looking at TREE.  Prints the procedures that show 'Changed since verification'.  A port to ui_port must
flip exactly the procedures whose sidecar lists the engine (and nothing else).  Never touches the lab registry (the registry file is a temp file).
"""
import sys
import tempfile
from pathlib import Path


def flips(base, tree):
    base, tree = Path(base).resolve(), Path(tree).resolve()
    sys.path.insert(0, str(tree))
    import procscan
    import verified

    def entries(root):
        return [verified.make_entry(p.name, p.model, str(root / p.launcher), base=root) for p in procscan.procs(root)]

    tmp = Path(tempfile.mkdtemp()) / 'reg.sqlite3'
    reg_base = verified.Registry(path=tmp, base=base, seed=False)
    for e in entries(base):
        reg_base.verify(e, who='ui_flips', on_date='2026-01-01', hardware='scratch')
    ents = entries(tree)
    status = verified.Registry(path=tmp, base=tree, seed=False).statuses(ents)
    return len(ents), sorted(e.name for e in ents if status[e.proc_key].kind == 'changed')


if __name__ == '__main__':
    total, changed = flips(*sys.argv[1:3])
    print(f'{total} procedures; {len(changed)} show Changed since verification:')
    for name in changed:
        print('  ', name)
