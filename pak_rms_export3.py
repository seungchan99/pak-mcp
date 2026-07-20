# -*- coding: utf-8 -*-
"""Export the current sheet's APS curves to Text (retry-safe) so we can compute
band-level RMS (0..1000 Hz). Output -> C:/MCPProject_pak/rms_export

    python pak_rms_export3.py
"""
from __future__ import annotations
import os, time
import tkinter as tk

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)
OUTDIR = "C:/MCPProject_pak/rms_export"
os.makedirs(OUTDIR, exist_ok=True)
for f in os.listdir(OUTDIR):
    try: os.remove(os.path.join(OUTDIR, f))
    except Exception: pass

tcl = tk.Tcl()
tcl.eval("source {%s}" % PAK_TCL_INIT)
tcl.eval("set pak_application")
tcl.eval("set reference [createobject $pak_application]")
tcl.eval("set gd [$reference GraphDef]")

def T(label, cmd, quiet=False):
    try:
        r = tcl.eval(cmd)
        if not quiet: print("  OK  %-22s -> %r" % (label, r))
        return True
    except Exception as exc:
        print("  ERR %-22s -> %s" % (label, str(exc).splitlines()[0][:70]))
        return False

T("Graphicoutput", "$gd Graphicoutput")
T("Graphic", "set g [$gd Graphic]")
# init viewer / export service
tcl.eval("catch {$g Plot}")
time.sleep(1.0)

got = False
for i in range(6):
    if T("Export (try %d)" % (i+1), "set exp [$g Export]", quiet=(i>0)):
        got = True; break
    time.sleep(0.8)
if not got:
    print("Export service not available -> abort"); raise SystemExit

# path FIRST, then format/selection
T("OutputPath Free", "$exp OutputPath {FreeSelection}")
T("FreeSelectionPath", "$exp FreeSelectionPath {%s}" % OUTDIR)
T("OutputFile", "$exp OutputFile {rms_out}")
T("Format Text", "$exp Format {Text}")
T("CurveSelection Sheet", "$exp CurveSelection {Sheet}")
T("ChannelSelection", "$exp ChannelSelection {OnlyMaster}")
T("FormatOptions", "set fo [$exp FormatOptions]")
T("Text opt", "set txt [$fo Text]")
T("Separator Tabs", "$txt Separator {Tabs}")
T("DecimalCharacter .", "$txt DecimalCharacter {.}")
T("OneFile on", "$txt OneFile {1}")
T("WithGraphicLabels", "$txt WithGraphicLabels {1}")
print("-- export --")
T("export", "$exp export")

for v in ("txt","fo","exp","g","gd","reference"):
    try: tcl.eval("catch {release $%s}; unset %s" % (v,v))
    except Exception: pass

print("\n=== files in %s ===" % OUTDIR)
for f in sorted(os.listdir(OUTDIR)):
    p = os.path.join(OUTDIR, f); sz = os.path.getsize(p)
    print("  %-40s %d B" % (f, sz))
    try:
        with open(p, "rb") as fh: raw = fh.read()
        txt = raw.decode("mbcs","replace")
        lines = txt.splitlines()
        print("    --- first 25 lines ---")
        for ln in lines[:25]:
            print("    " + ln[:160])
        print("    ... total %d lines" % len(lines))
    except Exception as e:
        print("    (read err)", e)
print("done.")
