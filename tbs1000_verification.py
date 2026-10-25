"""Tektronix TBS1000 and TBS1000C performance verification on the shared Tektronix engine (tds2000c_verification.py).

The procedure, prompts, stimulus (the scope option of a Fluke 5560A, 5522A or 5520A), uncertainty and report are the TDS2000C procedure's; each
family brings its own spec, model list, page references and oscilloscope driver:

  TBS1000   (non-C: TBS1022 / 1042 / 1062 / 1064 / 1102 / 1104 / 1152 / 1154)  specs/tektronix_tbs1000_pv.json, from the TBS1000 Series Service Manual
            077-0772-01 Rev D, Chapter 4.  Driver drivers/tektronix_tbs1000.py = the TDS2000C driver (same programmer manual 077-0444-03).
  TBS1000C  (TBS1052C / 1072C / 1102C / 1202C)  specs/tektronix_tbs1000c_pv.json, from the TBS1000C Specification and Performance Verification
            manual 077-1583-03 Rev A.  Driver drivers/tektronix_tbs1000c.py (TBS1000C Programmer Manual 077-1691-02).

Demo (no hardware):  python Procedures/Tektronix_TBS1000C_Verification.py --demo      (or Tektronix_TBS1000_Verification.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE))
import tds2000c_verification as T  # noqa: E402
import virtualbench  # noqa: E402
from ui_port import ui as port  # noqa: E402


def _tbs1000_driver():
    from drivers.tektronix_tbs1000 import TektronixTBS1000
    return TektronixTBS1000


def _tbs1000c_driver():
    from drivers.tektronix_tbs1000c import TektronixTBS1000C
    return TektronixTBS1000C


def _tbs1000_bench(model, cal):
    from drivers.simulated_tbs import make_tbs1000_bench
    return make_tbs1000_bench(model, cal)


def _tbs1000c_bench(model, cal):
    from drivers.simulated_tbs import make_tbs1000c_bench
    return make_tbs1000c_bench(model, cal)


TBS1000_FAMILY = T.Family(
    HERE / 'specs' / 'tektronix_tbs1000_pv.json', name='TBS1000', title='Tektronix TBS1000 (TBS1022 to TBS1154)', prefix='TBS', default_model='1104',
    settings_key='TBS1000', scope_label='TBS1000', addr_label='TBS1000 (USB)', log_name='TBS1000', diagram_prefix='hook_tbs1000',
    report_title='Tektronix TBS1000 performance verification', report_source='TBS1000 Series Service Manual 077-0772-01 Rev D, Chapter 4',
    pages=dict(warmup='4-3', selfcal='4-3', ext_figure='4-9'),
    scope_driver=_tbs1000_driver, sim_bench=_tbs1000_bench)

TBS1000C_FAMILY = T.Family(
    HERE / 'specs' / 'tektronix_tbs1000c_pv.json', name='TBS1000C', title='Tektronix TBS1000C (TBS1052C to TBS1202C)', prefix='TBS', default_model='1202C',
    settings_key='TBS1000C', scope_label='TBS1000C', addr_label='TBS1000C (USB)', log_name='TBS1000C', diagram_prefix='hook_tbs1000c',
    report_title='Tektronix TBS1000C performance verification',
    report_source='TBS1000C Specification and Performance Verification 077-1583-03 Rev A',
    pages=dict(warmup='24', selfcal='25', ext_figure='29'),
    ext_source='AUX', ext_title='Aux In edge trigger', ext_label='AUX IN',
    axis_hint='check HORizontal:MAIn:DELay:TIMe and WFMOutpre:XZEro on this firmware',
    scope_driver=_tbs1000c_driver, sim_bench=_tbs1000c_bench)


class TBS1000App(T.App):
    FAMILY = TBS1000_FAMILY


class TBS1000CApp(T.App):
    FAMILY = TBS1000C_FAMILY


def _main(app_cls, argv=None):
    argv = sys.argv if argv is None else argv

    def build(root):
        demo, fast = virtualbench.flags(argv)
        app_cls(root, demo=demo, fast_demo=fast)
    port.run_app(build)


def main_tbs1000(argv=None):
    _main(TBS1000App, argv)


def main_tbs1000c(argv=None):
    _main(TBS1000CApp, argv)
