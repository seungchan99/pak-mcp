# -*- coding: utf-8 -*-
"""Pin down the exact Sum-level-1 token. Row 1 currently reads 'BandpaÞ mag'
(U+00DE, not ß=U+00DF). Dump the codepoints, then test setting it via the
matching \\u00de escape, plus a pure-Tcl read->clear->restore round-trip.

    python pak_sumlevel_de.py
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
tcl.eval("set gd [$reference GraphDef]")
tcl.eval("set it [$gd Item 0]")
tcl.eval("set gp [$it GesPegel]")

def cur():
    try: return tcl.eval("$gp N1gesp")
    except Exception as exc: return "<err:%s>" % str(exc).splitlines()[0][:50]

c = cur()
print("current N1gesp = %r" % c)
print("codepoints     =", [hex(ord(ch)) for ch in c] if not c.startswith("<err") else "n/a")
print()

# 1) pure-Tcl round-trip: save -> clear -> restore (bytes never touch Python)
try:
    tcl.eval("set ORIG [$gp N1gesp]")
    tcl.eval("$gp N1gesp {-}")
    print("after clear    = %r" % cur())
    tcl.eval("$gp N1gesp $ORIG")
    print("after restore  = %r  <- Tcl-var round-trip" % cur())
except Exception as exc:
    print("round-trip FAIL:", str(exc).splitlines()[0][:60])

print()
# 2) construct the token with the matching escape(s)
for label, snip in [
    ('u00de (thorn)', r'$gp N1gesp "Bandpa\u00de mag"'),
    ('u00df (sz)',    r'$gp N1gesp "Bandpa\u00df mag"'),
]:
    # clear first so we can tell if it took
    try: tcl.eval("$gp N1gesp {-}")
    except Exception: pass
    try:
        tcl.eval(snip)
        after = cur()
        ok = after not in ("-", "") and not str(after).startswith("<err")
        print("  %-14s -> %s  (now %r)" % (label, "ACCEPT" if ok else "no-op", after))
    except Exception as exc:
        print("  %-14s -> FAIL: %s" % (label, str(exc).splitlines()[0][:55]))

# leave row 1 with the valid token restored
try: tcl.eval("$gp N1gesp $ORIG")
except Exception: pass
print("\nfinal N1gesp = %r" % cur())
for v in ("gp", "it", "gd", "reference"):
    try: tcl.eval("catch {release $%s}; unset %s" % (v, v))
    except Exception: pass
print("done.")
