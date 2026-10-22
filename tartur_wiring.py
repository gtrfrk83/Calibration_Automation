"""Glue between a verification engine's report points and tartur: the per-row TAR / TUR fields of an export.

Used by the multimeter engines (truevolt, dacq, 34401A, 8846A).  Handhelds and others build their own limits and call tartur directly.
Nothing here changes a report unless the 'Show TAR / TUR' choice is on; see report_pdf.apply_tar_tur.
"""
from __future__ import annotations


def point_limits(p):
    """(low, high) exactly as report_pdf.point_row derives them for the printed Tolerance - / Tolerance + cells."""
    low = p['low'] if 'low' in p else p['nominal'] - p['error']
    high = p['high'] if 'high' in p else p['nominal'] + p['error']
    return low, high


def point_fields(p, standard=None):
    """tartur.row_fields for a point_row-style point; `standard` must be the calibrator model passed to point_row (Uncertainty column).
    Blank fields on any problem (a report never fails because of an optional ratio)."""
    try:
        import tartur
        low, high = point_limits(p)
        return tartur.row_fields(p, low, high, standard=standard)
    except Exception:
        return dict(TAR='', TUR='')
