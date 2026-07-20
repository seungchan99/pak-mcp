# -*- coding: utf-8 -*-
"""List saved Graphic Definition files (PlotEditor) in PAK's table directories.

    python pak_list_graphdefs.py
"""
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

def prop(p):
    try: return tcl.eval("$reference %s" % p)
    except Exception as exc: return None

paths = {}
for p in ("Tablepath", "GroupStandards", "CompanyStandards", "Adminpath"):
    v = prop(p)
    print("%-16s = %r" % (p, v))
    if v: paths[p] = v

tcl.eval("catch {release $reference}; unset reference")

print("\n=== PlotEditor folders ===")
seen = set()
for label, base in paths.items():
    base = base.replace("\\", "/")
    for cand in (os.path.join(base, "PlotEditor"), base):
        cand = os.path.normpath(cand)
        if cand in seen or not os.path.isdir(cand):
            continue
        seen.add(cand)
        files = [f for f in sorted(os.listdir(cand)) if os.path.isfile(os.path.join(cand, f))]
        if files and ("PlotEditor" in cand):
            print("\n[%s]  (%s)" % (cand, label))
            for f in files:
                print("   ", f, " %d B" % os.path.getsize(os.path.join(cand, f)))
print("\ndone.")
