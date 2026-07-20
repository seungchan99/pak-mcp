# -*- coding: utf-8 -*-
"""End-to-end verify (pure COM/Tcl, no UI): build the 2-diagram comparison.
Diagram 1 = rows 1-3 Maximum, Diagram 2 = rows 4-6 Average [Q], then Graphic Output.
Run with PAK open. No Claude Desktop restart needed — this mirrors the server logic."""
import tkinter as tk
PAK_SOURCE = "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl"

STAT_MAP = {
    "-": "-", "Average [lin]": "Mittelwert   [lin]", "Average [Q]": "Mittelwert   [  Q]",
    "Maximum": "Maximum", "Minimum": "Minimum",
    "dB Average [lin]": "Mittelwert dB [lin]", "dB Average [Q]": "Mittelwert dB [  Q]",
}
RUNS = ["ExampleMOI/Acceleration_Run_01 [CP]",
        "ExampleMOI/Acceleration_Run_02 [CP]",
        "ExampleMOI/Acceleration_Run_03 [CP]"]
# (row, run_idx, diagram, curve, stat)
LAYOUT = [
    (1, 0, 1, 1, "Maximum"), (2, 1, 1, 2, "Maximum"), (3, 2, 1, 3, "Maximum"),
    (4, 0, 2, 1, "Average [Q]"), (5, 1, 2, 2, "Average [Q]"), (6, 2, 2, 3, "Average [Q]"),
]

tcl = tk.Tcl()
def ev(c): return tcl.eval(c)
def step(label, c):
    try:
        ev(c); return True
    except Exception as e:
        print("   [ERR] %s -> %s" % (label, str(e).splitlines()[0])); return False

for v in ["dt","tp","it","gd","reference"]:
    try: ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v,v,v))
    except Exception: pass

ev("source {%s}" % PAK_SOURCE)
ev("set reference [createobject $pak_application]")
ev("set gd [$reference GraphDef]")
ev("$gd Visible 1")

for row, ridx, diag, curve, stat in LAYOUT:
    ev("set it [$gd Item %d]" % (row-1))
    step("Active",  '$it Active 1')
    step("Diag",    '$it Diag %d' % diag)
    step("Curve",   '$it Curve %d' % curve)
    step("Datafile",'$it Datafile {%s}' % RUNS[ridx])
    ev("set dt [$it Datentyp]")
    step("SetChanpos",'$dt SetChanpos {Gear Lever} {+X} {Acceleration}')
    step("Mdtype",  '$dt Mdtype {Throughput}')
    step("Pdtype",  '$dt Pdtype {APS}')
    step("Srate",   '$dt Srate {32768}')
    ev("catch {release $dt}; unset dt")
    ev("set tp [$it TrackingParams]")
    step("Track",   '$tp SetChanposTrack {} {} {Time}')
    step("Start",   '$tp Start {Min}'); step("Stop", '$tp Stop {Max}')
    tok = STAT_MAP[stat]
    ok = step("Stats=%s" % stat, '$tp Stats {%s}' % tok)
    print("row %d: Diag %d Curve %d %s  Stats={%s} -> %s" % (row, diag, curve, RUNS[ridx].split('/')[-1], tok, "OK" if ok else "FAIL"))
    ev("catch {release $tp}; unset tp")
    ev("catch {release $it}; unset it")

okg = step("Graphicoutput", '$gd Graphicoutput')
print("\nGraphic Output -> %s" % ("OK" if okg else "FAIL"))
for v in ["gd","reference"]:
    try: ev("catch {release $%s}; unset %s" % (v,v))
    except Exception: pass
print("done. Check PAK: Diagram 1 = 3 Max curves, Diagram 2 = 3 Average curves (2D, overlaid).")
