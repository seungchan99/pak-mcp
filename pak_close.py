# -*- coding: utf-8 -*-
"""Close (hide) the PAK Graphic Definition window via COM."""
import tkinter as tk
PAK_SOURCE = "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl"
tcl = tk.Tcl()
def ev(c): return tcl.eval(c)
def try_ev(label, c):
    try: print("[OK] %-16s -> %r" % (label, ev(c))); return True
    except Exception as e: print("[ERR] %-15s -> %s" % (label, str(e).splitlines()[0])); return False

for v in ["gd","reference"]:
    try: ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v,v,v))
    except Exception: pass
ev("source {%s}" % PAK_SOURCE)
ev("set reference [createobject $pak_application]")
ev("set gd [$reference GraphDef]")
# close = hide the editor window
if not try_ev("Visible 0", "$gd Visible 0"):
    for m in ("Close", "SaveAndClose", "Save"):
        try_ev(m, "$gd %s" % m)
for v in ["gd","reference"]:
    try: ev("catch {release $%s}; unset %s" % (v,v))
    except Exception: pass
print("done. Graphic Definition window closed (hidden).")
