# -*- coding: utf-8 -*-
"""Band-pass RMS (Sum level 1 = Bandpass mag, 0..1000 Hz) for FR/RR x 3 runs.
COM config+output here; the UIA read runs in a SEPARATE process (pak_read_y1.py).

    python pak_band_rms.py
"""
from __future__ import annotations
import os, sys, subprocess
import tkinter as tk

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)
HERE = os.path.dirname(os.path.abspath(__file__))
BAND_FROM, BAND_TO = "0", "1000"
subs = ["Acceleration_Run_01","Acceleration_Run_02","Acceleration_Run_03"]
chans = [("Front Right","S","Sound Pressure"), ("Rear Right","S","Sound Pressure")]
targets = [(f"{p}/{s[-2:]}", f"ExampleMOI/{s} [CP]", p, d, q, s)
           for (p,d,q) in chans for s in subs]

tcl = tk.Tcl()
tcl.eval("source {%s}" % PAK_TCL_INIT)
tcl.eval("set pak_application")
def br(v): return "{%s}" % v

# capture band-pass token from row 1 (Tcl-internal, avoids umlaut encoding)
tcl.eval("set reference [createobject $pak_application]")
tcl.eval("set gd [$reference GraphDef]")
tcl.eval("set it [$gd Item 0]")
tcl.eval("set gp [$it GesPegel]")
tcl.eval("set SUMTOK [$gp N1gesp]")
disp = tcl.eval("set SUMTOK")
for v in ("gp","it","gd","reference"): tcl.eval("catch {release $%s}; unset %s" % (v,v))
if disp.strip() in ("-",""):
    print("Row1 Sum level 1 is not 'Band pass mag' -- set it once in PAK then rerun."); raise SystemExit

def read_via_subprocess(runtag):
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE,"pak_read_y1.py"), runtag],
                           capture_output=True, text=True, timeout=25)
        line = (r.stdout or "").strip().splitlines()[-1] if r.stdout.strip() else ""
        parts = line.split("\t")
        while len(parts) < 3: parts.append("")
        return parts[0], parts[1], parts[2]
    except Exception as e:
        return None, "SUBPROC ERR: %s" % e, ""

print("\nBand-pass RMS  band=%s..%s Hz\n" % (BAND_FROM, BAND_TO))
print("%-14s %-11s %-16s %s" % ("target","X1","Y1(value)","channel"))
for (label, meas, pos, dr, q, subname) in targets:
    tcl.eval("set reference [createobject $pak_application]")
    tcl.eval("set gd [$reference GraphDef]")
    tcl.eval("set it [$gd Item 0]")
    tcl.eval("$it Active 1"); tcl.eval("$it Diag 1"); tcl.eval("$it Curve 1")
    tcl.eval("$it Datafile %s" % br(meas))
    tcl.eval("set dt [$it Datentyp]")
    tcl.eval("$dt SetChanpos %s %s %s" % (br(pos), br(dr), br(q)))
    tcl.eval("$dt Mdtype %s" % br("Throughput"))
    tcl.eval("$dt Srate %s" % br("32768"))
    tcl.eval("$dt Pdtype %s" % br("APS"))
    tcl.eval("$dt Bplevelfrom %s" % br(BAND_FROM))
    tcl.eval("$dt Bplevelto %s" % br(BAND_TO))
    tcl.eval("catch {release $dt}; unset dt")
    tcl.eval("set gp [$it GesPegel]")
    tcl.eval("$gp N1gesp $SUMTOK")
    tcl.eval("catch {release $gp}; unset gp")
    tcl.eval("catch {release $it}; unset it")
    for rn in range(2, 9):
        tcl.eval("set it2 [$gd Item %d]" % (rn-1))
        tcl.eval("$it2 Active 0"); tcl.eval("catch {release $it2}; unset it2")
    tcl.eval("$gd Graphicoutput")
    for v in ("gd","reference"): tcl.eval("catch {release $%s}; unset %s" % (v,v))
    x1,y1,banner = read_via_subprocess(subname)
    ch = banner.split("Channel:")[-1].strip() if "Channel:" in banner else ""
    print("%-14s %-11s %-16s %s" % (label, x1, y1, ch))
print("\ndone.")
