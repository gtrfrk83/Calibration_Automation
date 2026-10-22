"""Test helper: the registration text the Manager used to hold by hand, rebuilt from the scanned procedures (procscan.py).

Older tests asserted that Calibration_Procedure_Manager.py LISTED a procedure by looking for these strings in its source.  The Manager now finds
procedures by scanning Procedures/*.procedure.json, so those tests ask for the same strings built from the scan; a procedure that is not
registered is still missing from the text and the test still fails.  Test helper only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import procscan  # noqa: E402


def manager_text(base=ROOT) -> str:
    procs = procscan.procs(base)
    stable, versions = procscan.legacy_tables(procs)
    lines = ['STABLE = {'] + [f" '{n}': '{f}'," for n, f in stable.items()] + ['}', 'VERSIONS = {']
    lines += [f" '{f}': '{v}'," for f, v in versions.items()] + ['}', 'records = [']
    lines += ["('%s','%s','%s','%s','%s')," % p.registration for p in procs] + [']']
    return '\n'.join(lines)
