# -*- coding: utf-8 -*-
"""Configure FR/RR x 3 as APS + Sum level 1 (Bandpass mag, 0..1000 Hz), Graphic
Output, then screenshot the Graphic Viewer -> C:/MCPProject_pak/rms_shot.png
(so the drawn band-pass values can be read from the image).

    python pak_rms_shot.py
"""
from __future__ import annotations
import os, time
import tkinter as tk

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)
OUT = "C:/MCPProject_pak/rms_shot.png"
BAND_FROM, BAND_TO = "0", "1000"
subs = ["Acceleration_Run_01","Acceleration_Run_02","Acceleration_Run_03"]

tcl = tk.Tcl()
tcl.eval("source {%s}" % PAK_TCL_INIT)
tcl.eval("set pak_application")
def br(v): return "{%s}" % v

tcl.eval("set reference [createobject $pak_application]")
tcl.eval("set gd [$reference GraphDef]")
# capture token
tcl.eval("set it [$gd Item 0]"); tcl.eval("set gp [$it GesPegel]")
tcl.eval("set SUMTOK [$gp N1gesp]")
disp = tcl.eval("set SUMTOK")
tcl.eval("catch {release $gp}; unset gp"); tcl.eval("catch {release $it}; unset it")
print("Sum level token:", repr(disp))

def cfg(row, diag, curve, meas, pos, dr, q):
    tcl.eval("set it [$gd Item %d]" % (row-1))
    tcl.eval("$it Active 1"); tcl.eval("$it Diag %d" % diag); tcl.eval("$it Curve %d" % curve)
    tcl.eval("$it Datafile %s" % br(meas))
    tcl.eval("set dt [$it Datentyp]")
    tcl.eval("$dt SetChanpos %s %s %s" % (br(pos), br(dr), br(q)))
    tcl.eval("$dt Mdtype %s" % br("Throughput")); tcl.eval("$dt Srate %s" % br("32768"))
    tcl.eval("$dt Pdtype %s" % br("APS"))
    tcl.eval("$dt Bplevelfrom %s" % br(BAND_FROM)); tcl.eval("$dt Bplevelto %s" % br(BAND_TO))
    tcl.eval("catch {release $dt}; unset dt")
    tcl.eval("set gp [$it GesPegel]"); tcl.eval("$gp N1gesp $SUMTOK")
    tcl.eval("catch {release $gp}; unset gp")
    tcl.eval("catch {release $it}; unset it")

row=1
for c,s in enumerate(subs,1): cfg(row,1,c,f"ExampleMOI/{s} [CP]","Front Right","S","Sound Pressure"); row+=1
for c,s in enumerate(subs,1): cfg(row,2,c,f"ExampleMOI/{s} [CP]","Rear Right","S","Sound Pressure"); row+=1
# deactivate leftovers
for rn in range(7,13):
    tcl.eval("set it [$gd Item %d]" % (rn-1)); tcl.eval("$it Active 0"); tcl.eval("catch {release $it}; unset it")
tcl.eval("$gd Graphicoutput")
for v in ("gd","reference"): tcl.eval("catch {release $%s}; unset %s" % (v,v))
print("Graphic Output done; capturing...")
time.sleep(2.0)

# find viewer rect + screenshot
try:
    import uiautomation as auto
    from PIL import ImageGrab
except Exception as e:
    print("need pillow (pip install pillow):", e); raise SystemExit
win=None
for w in auto.GetRootControl().GetChildren():
    try:
        if w.ControlTypeName=="WindowControl" and "graphic viewer" in (w.Name or "").lower():
            win=w; break
    except Exception: pass
if not win:
    print("Graphic Viewer not found"); raise SystemExit
try: win.SetActive()
except Exception: pass
time.sleep(0.5)
r=win.BoundingRectangle
bbox=(r.left, r.top, r.right, r.bottom)
img=ImageGrab.grab(bbox=bbox, all_screens=True)
img.save(OUT)
print("saved:", OUT, "size", img.size, "bbox", bbox)
print("done.")
