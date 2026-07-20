# -*- coding: utf-8 -*-
"""Test the hypothesis: Sum level 1 = 'Bandpa\u00df mag' only appears in N1gesp's
selection list AFTER the row is configured as an APS spectrum with a band-pass
range. So configure Datentyp FIRST, then set N1gesp via the Tcl \\u00df escape.

    python pak_set_sumlevel_after_cfg.py

Uses row 1 + ExampleMOI/Acceleration_Run_01 Gear Lever +X, band 0..1000.
"""
from __future__ import annotations
import os
import tkinter as tk

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)
MEAS = "ExampleMOI/Acceleration_Run_01 [CP]"
POS, DR, Q = "Gear Lever", "+X", "Acceleration"
BAND_FROM, BAND_TO = "0", "1000"

tcl = tk.Tcl()
tcl.eval("source {%s}" % PAK_TCL_INIT)
tcl.eval("set pak_application")
def br(v): return "{%s}" % v

tcl.eval("set reference [createobject $pak_application]")
tcl.eval("set gd [$reference GraphDef]")
tcl.eval("set it [$gd Item 0]")

# 1) configure the data type FIRST (APS spectrum + band-pass range)
tcl.eval("$it Active 1"); tcl.eval("$it Diag 1"); tcl.eval("$it Curve 1")
tcl.eval("$it Datafile %s" % br(MEAS))
tcl.eval("set dt [$it Datentyp]")
tcl.eval("$dt SetChanpos %s %s %s" % (br(POS), br(DR), br(Q)))
tcl.eval("$dt Mdtype %s" % br("Throughput"))
tcl.eval("$dt Srate %s" % br("32768"))
tcl.eval("$dt Pdtype %s" % br("APS"))
tcl.eval("$dt Bplevelfrom %s" % br(BAND_FROM))
tcl.eval("$dt Bplevelto %s" % br(BAND_TO))
tcl.eval("catch {release $dt}; unset dt")
print("configured row 1 as APS, band %s..%s" % (BAND_FROM, BAND_TO))

# 2) now try to set the band-pass sum level
tcl.eval("set gp [$it GesPegel]")
def cur():
    try: return tcl.eval("$gp N1gesp")
    except Exception as exc: return "<err:%s>" % str(exc).splitlines()[0][:50]
print("N1gesp before =", repr(cur()))

attempts = [
    ('tcl \\u00df via var', r'set _tok "Bandpa\u00df mag"; $gp N1gesp $_tok'),
    ('tcl \\u00df direct',  r'$gp N1gesp "Bandpa\u00df mag"'),
    ('ascii Bandpass mag',  r'$gp N1gesp {Bandpass mag}'),
]
for label, snip in attempts:
    try:
        tcl.eval(snip)
        after = cur()
        ok = after not in ("-", "") and not str(after).startswith("<err")
        print("  %-20s -> %s  (N1gesp now %r)" % (label, "ACCEPT" if ok else "no-op", after))
        if ok:
            print("\n  >>> WORKS: %s  token=%r" % (label, after))
            break
    except Exception as exc:
        print("  %-20s -> FAIL: %s" % (label, str(exc).splitlines()[0][:60]))

print("\nfinal N1gesp =", repr(cur()))
for v in ("gp", "it", "gd", "reference"):
    try: tcl.eval("catch {release $%s}; unset %s" % (v, v))
    except Exception: pass
print("done.")
