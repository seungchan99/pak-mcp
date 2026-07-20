# -*- coding: utf-8 -*-
"""X(freq)=lin 0..2000, Y level = Auto (from/to Auto), re-plot row 1."""
from __future__ import annotations
import os
import tkinter as tk

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)
tcl = tk.Tcl()
tcl.eval("source {%s}" % PAK_TCL_INIT)
tcl.eval("set pak_application")
tcl.eval("set reference [createobject $pak_application]")
tcl.eval("set gd [$reference GraphDef]")
tcl.eval("set it [$gd Item 0]")
tcl.eval("set sd [$it SkalenDefinition]")
tcl.eval("set ax [$sd AchsenSkalierung]")

def setp(field, val):
    try:
        tcl.eval("$ax %s {%s}" % (field, val)); print("  OK  %s = %s" % (field, val)); return True
    except Exception as exc:
        print("  ERR %s = %s -> %s" % (field, val, str(exc).splitlines()[0][:45])); return False

# X axis (freq) fixed 0..2000
setp("Aktiv1_","1"); setp("Type1_","lin"); setp("Von1_","0"); setp("Bis1_","2000")
# Y axis (level) auto -> try Auto, fallback OFF
if not setp("Von2_","Auto"): setp("Von2_","OFF")
if not setp("Bis2_","Auto"): setp("Bis2_","OFF")

print("slots:")
for n in (1,2,3):
    print("  slot%d: Aktiv=%s Type=%r Von=%r Bis=%r" % (
        n, tcl.eval("$ax Aktiv%d_" % n), tcl.eval("$ax Type%d_" % n),
        tcl.eval("$ax Von%d_" % n), tcl.eval("$ax Bis%d_" % n)))
for v in ("ax","sd"): tcl.eval("catch {release $%s}; unset %s" % (v,v))
tcl.eval("catch {release $it}; unset it")
tcl.eval("$gd Graphicoutput"); print("Graphicoutput OK -> diagram 1: X 0..2000 Hz, Y Auto ?")
for v in ("gd","reference"): tcl.eval("catch {release $%s}; unset %s" % (v,v))
print("done.")
