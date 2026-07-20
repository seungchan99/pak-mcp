# -*- coding: utf-8 -*-
"""Fix axes on row 1: X(freq)=lin 0..2000, Y(level)=dB 0..1000, re-plot."""
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

cmds = [
    "Aktiv1_ 1", "Type1_ {lin}", "Von1_ 0", "Bis1_ 2000",   # X = frequency
    "Aktiv2_ 1", "Type2_ {dB}",  "Von2_ 0", "Bis2_ 1000",   # Y = level dB
]
for c in cmds:
    try:
        tcl.eval("$ax %s" % c); print("  OK ", c)
    except Exception as exc:
        print("  ERR", c, "->", str(exc).splitlines()[0][:55])
print("slots:")
for n in (1,2,3):
    print("  slot%d: Aktiv=%s Type=%r Von=%r Bis=%r" % (
        n, tcl.eval("$ax Aktiv%d_" % n), tcl.eval("$ax Type%d_" % n),
        tcl.eval("$ax Von%d_" % n), tcl.eval("$ax Bis%d_" % n)))
for v in ("ax","sd"): tcl.eval("catch {release $%s}; unset %s" % (v,v))
tcl.eval("catch {release $it}; unset it")
tcl.eval("$gd Graphicoutput"); print("Graphicoutput OK -> diagram 1: X 0..2000 Hz, Y dB 0..1000 ?")
for v in ("gd","reference"): tcl.eval("catch {release $%s}; unset %s" % (v,v))
print("done.")
