"""Subprocess helper for tests/test_tartur_wiring_scopes.py:  python tartur_scopes_harness.py ROOT OUTDIR SHOW [PER_KIND]
SHOW is off | on | tar | tur.  Runs the MDO4000C and function generator procedures against the simulated benches (drivers/simulated_*.py;
points the simulated sources cannot make fall back to the engine's demo_reading), builds the WaveSurfer demo data, then calls the engines' real
export_pdf / export_pdf_report / export_calibration_section code with stubbed tkinter, a pinned clock and a fake report dialog.
ROOT is the code tree to exercise (the branch or a baseline checkout); PDFs land in OUTDIR."""
import sys, os, json, tempfile, collections
root, out, show = sys.argv[1:4]
PER_KIND = int(sys.argv[4]) if len(sys.argv) > 4 else 3
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root); sys.path.insert(0, root + '/Procedures')
os.makedirs(out, exist_ok=True)
tmp = tempfile.mkdtemp(); os.environ['CALSUITE_DATA'] = tmp; os.environ['HOME'] = tmp
import time as _t; _t.sleep = lambda s: None
import importlib.util
spec = importlib.util.spec_from_file_location('tk_stub', os.path.join(HERE, '_tk_stub.py'))
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st); st.install()

def mdo_found():
    import mdo4000c_verification as M
    from drivers.simulated_mdo import make_mdo_bench
    M.SLEEP_SCALE = 0
    bench, t = make_mdo_bench()
    io = M.IO(dict(cal_baud=9600), transports=t)
    cfg = M.Config(model='4104C', sa='SA6', afg=True, dvm=True, tpa=True)
    class FakeApp:
        stop = False
        def __init__(s): s.io, s.cfg = io, cfg
        def request(s, kind, payload=None):
            return payload['p']['nominal'] if kind == 'manual' else True
        def post(s, *a, **k): pass
    runner = M.Runner(FakeApp())
    seen = collections.Counter(); found = {}
    for p in M.POINTS:
        if not cfg.applies(p) or seen[p['kind']] >= PER_KIND:
            continue
        seen[p['kind']] += 1
        try:
            out_ = runner.run_point(p)
            reading, raw = out_ if isinstance(out_, tuple) else (out_, {})
        except Exception:
            reading, raw = M.demo_reading(p), {}
        raw = dict(raw, reading=reading)
        found[str(p['id'])] = dict(reading=reading, raw=raw, result=M.judge(p, reading), synthetic=False,
                                   uncertainty=M.uncertainty_text(p, raw), timestamp='2026-01-02T03:04:05', data='As Found')
    return found


def fgen_found():
    import fgen_verification as F
    from drivers.simulated_fgen import make_fgen_bench
    F.configure('33220A')
    bench, t = make_fgen_bench(F.MODEL)
    io = F.IO({}, transports=t, ask_number=lambda prompt, unit: 0.0)
    res, cache = {}, {}
    for p in F.POINTS:
        try:
            v, raw = io.measure(p, res, cache)
        except Exception:
            v, raw = F.demo_reading(p)
        res[str(p['id'])] = dict(reading=v, raw=raw, result=F.judge(p, v), synthetic=False, timestamp='2026-01-02T03:04:05')
    return res

from datetime import datetime
import types
FIXED=datetime(2026,1,2,3,4)
class Clock(datetime):
    @classmethod
    def now(cls,tz=None): return FIXED
import reportlab.rl_config as rc; rc.invariant=1
import report_pdf
report_pdf.datetime=Clock
if show=='off': details_flag={}
elif show=='on': details_flag={'show_tar_tur':True}
else:
    details_flag={'show_tar_tur':report_pdf.TarTur(show=='tar',show=='tur')}
class V:
    def __init__(s,v=''): s.v=v
    def get(s): return s.v
    def set(s,v): s.v=v
current={}
def ask_details(parent,procedure=''):
    return dict({'technician':'T','temperature':'23','humidity':'45','standards':[],'procedure':procedure},**details_flag)
fake=types.ModuleType('report_dialog'); fake.ask_details=ask_details; sys.modules['report_dialog']=fake
import tkinter
def save(*a,**k): return current['path']
tkinter.filedialog.asksaveasfilename=save
errors=[]
tkinter.messagebox.showerror=lambda *a,**k: errors.append(a)
tkinter.messagebox.showinfo=lambda *a,**k: None
tkinter.messagebox.showwarning=lambda *a,**k: None

# ---- MDO
import mdo4000c_verification as M
# (a ported engine has no filedialog / messagebox name: the port calls tkinter's, patched above)
found=mdo_found()
app=M.App.__new__(M.App)
app.cfg=M.Config(model='4104C',sa='SA6',afg=True,dvm=True,tpa=True); app._found=found; app._left={k:dict(v,reading=v['reading']*1.0001 if isinstance(v['reading'],(int,float)) else v['reading']) for k,v in list(found.items())[10:40]}
app.asset=V('A1'); app.serial=V('S1'); app.status=V(); app.root=None
app.any_synthetic=lambda: False
current['path']=out+'/mdo.pdf'; app.export_pdf()
# ---- FGEN
import fgen_verification as F
F.configure('33220A')
app=F.App.__new__(F.App)
app._found=fgen_found(); app._left={k:dict(v,reading=v['reading']*1.0001) for k,v in list(app._found.items())[2:9]}
app.asset=V('A1'); app.serial=V('S1'); app.status=V(); app.root=None; app.period=V('1 year')
app.any_synthetic=lambda: False
current['path']=out+'/fgen.pdf'; app.export_pdf()
# ---- WaveSurfer
import WaveSurfer_WS4104HD as W
W.filedialog.asksaveasfilename=save; W.messagebox.showerror=lambda *a,**k: errors.append(a)
W.messagebox.showinfo=lambda *a,**k: None; W.messagebox.showwarning=lambda *a,**k: None
app=W.RMSNoiseApp.__new__(W.RMSNoiseApp)
for a in ('rows','dc_rows','imp_rows','offset_rows','bw_rows','tb_rows','trig_rows'): setattr(app,a,[])
app.root=st._Dummy(); app.demo_mode=False
for n in dir(W.RMSNoiseApp):
    if n.startswith('refresh_') or n.startswith('render_'): setattr(app,n,lambda *a,**k: None)
app.add_result=lambda r: app.rows.append(r)
app.imp_progress={}; 
class SV(V):
    pass
for n in ('status','dc_status','imp_status','offset_status','bw_status','tb_status','trig_status','instrument_id','serial'): setattr(app,n,V('A1' if n=='instrument_id' else ''))
app.sync_asset=lambda: True
app._mode=W.datamode.FOUND
app.any_synthetic=lambda: False
saved=W.messagebox.showinfo
W.RMSNoiseApp.__getattr__=lambda self,n: (_ for _ in ()).throw(AttributeError(n)) if n.startswith('__') else V('10')
app.load_demo_data()
del W.RMSNoiseApp.__getattr__
app.demo_mode=False
W.RMSNoiseApp.any_synthetic=lambda self: False
W_attrs={a:getattr(app,a) for a in W.RMSNoiseApp._SET_ATTRS if a!='run_config'}
left={a:(list(map(dict,v[:3])) if isinstance(v,list) else v) for a,v in W_attrs.items()}
for a in left:
    for r in left[a]: r.update({k:r[k]*1.001 for k in ('measured_v','measured_ohm','response_db','error_hz') if k in r})
left['run_config']=None
app._mode_sets={W.datamode.LEFT:left}
current['path']=out+'/ws_all.pdf'; app.export_pdf_report()
for kind,meth in (('dcv','export_dcv'),('impedance','export_impedance'),('offset','export_offset'),('bandwidth','export_bandwidth')):
    current['path']=out+f'/ws_{kind}.pdf'; getattr(app,meth)()
current['path']=out+'/ws_noise.pdf'; app.export_calibration_section('noise')
print('errors',errors)
