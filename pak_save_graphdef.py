# -*- coding: utf-8 -*-
"""Save the current Graphic Definition to a file NOW (before the server reload).

    python pak_save_graphdef.py MOI_Analysis
    python pak_save_graphdef.py "C:/PakData/Tables/PlotEditor/MOI_Analysis"

A bare name is saved to PAK's user Tables (PlotEditor) directory.
"""
from __future__ import annotations
import os, sys
import tkinter as tk

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)
fname = sys.argv[1] if len(sys.argv) > 1 else "MOI_Analysis"

tcl = tk.Tcl()
tcl.eval("source {%s}" % PAK_TCL_INIT)
tcl.eval("set pak_application")
tcl.eval("set reference [createobject $pak_application]")
tcl.eval("set gd [$reference GraphDef]")
try:
    tcl.eval("$gd SaveAs {%s}" % fname)
    print("SaveAs OK ->", fname)
    try:
        print("Name:", tcl.eval("$gd Name"))
    except Exception:
        pass
except Exception as exc:
    print("SaveAs ERR:", str(exc).splitlines()[0])
for v in ("gd", "reference"):
    try: tcl.eval("catch {release $%s}; unset %s" % (v, v))
    except Exception: pass
print("done.")
