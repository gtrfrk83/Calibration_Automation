#!/usr/bin/env python3
"""Export one procedure of this suite into a package zip (see packages.py for the format).

    python tools/make_package.py Fluke_117_Verification --out \\\\server\\lab\\procedure_library
    python tools/make_package.py Keithley_2000_Verification --author "Mike" --verified-mark
    python tools/make_package.py --list

The package holds the procedure's own files (its sidecar Procedures/<id>.procedure.json, launcher, spec / driver / tests that belong to it alone,
and the hook-up diagrams that match its prefixes). Files the procedure shares with others (engines, the calibrator driver, a shared spec) are NOT
shipped; the package lists them as `requires` and the suite that imports it must already have them. Add more with --include <path> (a file under
Procedures/, specs/, drivers/, diagrams/ or tests/).

--verified-mark adds the lab's verified-on-hardware mark (date, name, fingerprint of the files). It is only added when the procedure is verified,
locked and unchanged, and the model has no saved procedure changes. The importing suite honours it only if its installed files give the same
fingerprint. The seeded-verified flag of the lab owner is never exported.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import packages  # noqa: E402
import procscan  # noqa: E402
import verified  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('procedure', nargs='?', help='procedure id (the launcher name without .py) or launcher file name')
    ap.add_argument('--out', default='.', help='folder for the zip (default: here)')
    ap.add_argument('--base', default=str(HERE), help='the suite folder to export from (default: this one)')
    ap.add_argument('--include', action='append', default=[], metavar='PATH', help='an extra file to ship, relative to the suite folder')
    ap.add_argument('--author', default='', help='who made the package (shown in the preview as a claim)')
    ap.add_argument('--min-suite', default=None, help='minimum suite version, e.g. v70 (default: this suite)')
    ap.add_argument('--verified-mark', action='store_true', help='add the verified-on-hardware mark (only if verified, locked and unchanged)')
    ap.add_argument('--registry', default=None, help='lab_registry.sqlite3 to read the verified record from (default: the real one)')
    ap.add_argument('--list', action='store_true', help='list the procedures that can be exported')
    args = ap.parse_args(argv)
    base = Path(args.base)
    if args.list or not args.procedure:
        for p in procscan.procs(base):
            print(f'{p.id:40s} v{p.version:4s} {p.name}')
        return 0
    registry = verified.Registry(args.registry, base=base) if args.registry else verified.Registry(base=base)
    try:
        path = packages.build_package(args.procedure, base, args.out, registry=registry, extra_files=args.include, with_verified_mark=args.verified_mark,
                                      author=args.author, min_suite=args.min_suite)
    except packages.PackageError as ex:
        print(f'Not exported: {ex}', file=sys.stderr)
        return 2
    print(f'Wrote {path}  (sha256 {packages.sha256_file(path)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
