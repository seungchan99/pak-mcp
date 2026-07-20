# -*- coding: utf-8 -*-
"""Save the current PAK Graphic Definition to a file via COM, then locate the
file and dump every TrackingParams STATS line with context — so we can learn the
exact save-file format for the file-edit approach (save -> edit STATS -> reload).

Run with PAK open (Graphic Definition loaded).
"""
import os, glob, time
import tkinter as tk

PAK_SOURCE = "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl"
OUT_DIR = "C:/MCPProject_pak"
tcl = tk.Tcl()
def ev(c): return tcl.eval(c)
def try_ev(c):
    try: return True, ev(c)
    except Exception as e: return False, str(e).splitlines()[0]

for v in ["gd", "reference"]:
    try: ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v, v, v))
    except Exception: pass
ev("source {%s}" % PAK_SOURCE)
ev("set reference [createobject $pak_application]")
ev("set gd [$reference GraphDef]")
print("methods on gd:", [m for m in dir] if False else "")
print("--- trying to save ---")

# candidate save calls (Editor interface: Save / SaveAs)
candidates = [
    'set p {%s/pakdef_dump.txt}; $gd SaveAs $p' % OUT_DIR,
    'set p {%s/pakdef_dump}; $gd SaveAs $p' % OUT_DIR,
    'set p {%s/pakdef_dump.glue}; $gd SaveAs $p' % OUT_DIR,
    '$gd Save',
]
saved_path = None
for c in candidates:
    ok, info = try_ev(c)
    print("[%s] %s -> %s" % ("OK" if ok else "ERR", c, info))
    if ok and "SaveAs" in c:
        # extract path
        for tok in c.split("{"):
            if "}" in tok:
                saved_path = tok.split("}")[0]
        break

try_ev("catch {release $gd}; unset gd")
try_ev("catch {release $reference}; unset reference")

# find candidate files: our OUT_DIR + PAK project dirs, recently modified, containing STATS
print("\n--- searching for definition files containing STATS/TrackingParams ---")
search_dirs = [OUT_DIR, "C:/MCPProject", os.path.expanduser("~"),
               "C:/ProgramData", "C:/Users/Public"]
hits = []
for d in search_dirs:
    for pat in ("*.txt", "*.glue", "*.gd", "*.dat", "*"):
        for f in glob.glob(os.path.join(d, pat)):
            try:
                if os.path.getmtime(f) < time.time() - 3600:
                    continue
                if os.path.getsize(f) > 5_000_000:
                    continue
                data = open(f, "rb").read()
                if b"TrackingParams" in data or b"STATS" in data:
                    hits.append(f)
            except Exception:
                pass
hits = sorted(set(hits))
print("files with STATS/TrackingParams (modified < 1h):", hits[:20])

for f in hits[:5]:
    print("\n===== %s =====" % f)
    try:
        txt = open(f, encoding="mbcs", errors="replace").read()
    except Exception as e:
        print("read err", e); continue
    lines = txt.splitlines()
    for i, ln in enumerate(lines):
        if "STATS" in ln:
            lo = max(0, i - 2); hi = min(len(lines), i + 2)
            print("  ...", " / ".join(x.strip() for x in lines[lo:hi]))
print("\ndone.")
