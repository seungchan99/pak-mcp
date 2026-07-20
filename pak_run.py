# -*- coding: utf-8 -*-
"""One-shot PAK comparison builder.

Single command that:
  1) COM/Tcl : sets rows 1-6 (channel, Throughput, APS, Srate, Diagram, Curve,
     measurement, Time track Min..Max)  -- no mouse, API level
  2) UI-Auto : sets each row's Track 'Stat. parameter' (the ONE field PAK does not
     expose over COM) using UI-Automation *patterns* (Invoke/SetValue/Select),
     not pixel/mouse macros
  3) COM/Tcl : runs Graphic Output

Default layout:  Diagram 1 = rows 1-3 (Maximum) ,  Diagram 2 = rows 4-6 (Average [Q])

Requires:  pip install uiautomation      (mcp not needed here)
Usage:
  python pak_run.py
  python pak_run.py --stat1 Maximum --stat2 "Average [Q]"
"""
import sys, time, argparse
import tkinter as tk
try:
    import uiautomation as auto
except Exception:
    print("ERROR: pip install uiautomation"); sys.exit(1)

PAK_SOURCE = "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl"
CHANNEL = ("Gear Lever", "+X", "Acceleration")
MDTYPE, PDTYPE, SRATE = "Throughput", "APS", "32768"
RUNS = ["ExampleMOI/Acceleration_Run_01 [CP]",
        "ExampleMOI/Acceleration_Run_02 [CP]",
        "ExampleMOI/Acceleration_Run_03 [CP]"]
# (row, run_index, diagram, curve)
LAYOUT = [(1, 0, 1, 1), (2, 1, 1, 2), (3, 2, 1, 3),
          (4, 0, 2, 1), (5, 1, 2, 2), (6, 2, 2, 3)]

_tcl = tk.Tcl()
def ev(c): return _tcl.eval(c)


# ---------- 1) DATA via COM/Tcl ----------
def setup_data():
    for v in ["dt", "tp", "it", "gd", "reference"]:
        try: ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v, v, v))
        except Exception: pass
    ev("source {%s}" % PAK_SOURCE)
    ev("set reference [createobject $pak_application]")
    ev("set gd [$reference GraphDef]")
    ev("$gd Visible 1")
    pos, dr, qt = CHANNEL
    for row, ridx, diag, curve in LAYOUT:
        ev("set it [$gd Item %d]" % (row - 1))
        ev("$it Active 1"); ev("$it Diag %d" % diag); ev("$it Curve %d" % curve)
        ev("$it Datafile {%s}" % RUNS[ridx])
        ev("set dt [$it Datentyp]")
        ev("$dt SetChanpos {%s} {%s} {%s}" % (pos, dr, qt))
        ev("$dt Mdtype {%s}" % MDTYPE); ev("$dt Pdtype {%s}" % PDTYPE); ev("$dt Srate {%s}" % SRATE)
        ev("catch {release $dt}; unset dt")
        ev("set tp [$it TrackingParams]")
        ev("$tp SetChanposTrack {} {} {Time}"); ev("$tp Start {Min}"); ev("$tp Stop {Max}")
        ev("catch {release $tp}; unset tp")
        ev("catch {release $it}; unset it")
    ev("catch {release $gd}; unset gd")
    ev("catch {release $reference}; unset reference")
    print("[1] data set for rows 1-6 (COM/Tcl).")


def graphic_output():
    for v in ["gd", "reference"]:
        try: ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v, v, v))
        except Exception: pass
    ev("set reference [createobject $pak_application]")
    ev("set gd [$reference GraphDef]")
    ev("$gd Graphicoutput")
    ev("catch {release $gd}; unset gd")
    ev("catch {release $reference}; unset reference")
    print("[3] Graphic Output executed (COM/Tcl).")


# ---------- 2) STAT. PARAMETER via UI-Automation patterns ----------
def find_window(substr):
    for w in auto.GetRootControl().GetChildren():
        try:
            if substr.lower() in (w.Name or "").lower():
                return w
        except Exception:
            pass
    return None


def data_def_cells(grid):
    cells, stack = [], [grid]
    while stack:
        n = stack.pop()
        try:
            nm = n.Name or ""
            if n.ControlTypeName == "ButtonControl" and " Pos." in nm and ("(2D)" in nm or "(3D)" in nm):
                cells.append(n)
        except Exception:
            pass
        try:
            stack.extend(n.GetChildren())
        except Exception:
            pass
    uniq = {}
    for c in cells:
        try: uniq[c.BoundingRectangle.top] = c
        except Exception: pass
    return [uniq[k] for k in sorted(uniq)]


def invoke(ctrl):
    """Trigger a control via UIA patterns (no mouse). Returns True on success."""
    for getter in ("GetInvokePattern", "GetLegacyIAccessiblePattern"):
        try:
            p = getattr(ctrl, getter)()
            if getter == "GetInvokePattern":
                p.Invoke()
            else:
                p.DoDefaultAction()
            return True
        except Exception:
            continue
    return False


def open_row_dialog(cell):
    # try pattern invoke first (no mouse); grid cells usually open on double action
    invoke(cell)
    time.sleep(0.5)
    if find_window("Data definition to No"):
        return True
    # fallback: UIA double-click (moves mouse, but still element-targeted)
    try:
        cell.DoubleClick(waitTime=0.3)
    except Exception:
        pass
    time.sleep(0.5)
    return find_window("Data definition to No") is not None


def find_stat_combo(win):
    found, stack = [], [win]
    while stack:
        n = stack.pop()
        try:
            if n.ControlTypeName == "ComboBoxControl" and (n.Name or "") == "Additional Calculations":
                found.append(n)
        except Exception:
            pass
        try:
            stack.extend(n.GetChildren())
        except Exception:
            pass
    found.sort(key=lambda c: (c.BoundingRectangle.top if c.BoundingRectangle else 0))
    return found[0] if found else None


def set_combo(combo, value):
    # ValuePattern first (pure API)
    try:
        combo.GetValuePattern().SetValue(value)
        if combo.GetValuePattern().Value == value:
            return True
    except Exception:
        pass
    # else expand + SelectionItemPattern on the item
    try:
        combo.Select(value)
        return True
    except Exception:
        return False


def set_stats(stat_map):
    grid = find_window("Graphic Definition")
    if not grid:
        print("[2] Graphic Definition window not found."); return
    grid.SetActive(); time.sleep(0.3)
    cells = data_def_cells(grid)
    print("[2] %d rows detected for stat setting." % len(cells))
    for i, cell in enumerate(cells, start=1):
        if i not in stat_map:
            continue
        target = stat_map[i]
        if not open_row_dialog(cell):
            print("    row %d: dialog didn't open" % i); continue
        dlg = find_window("Data definition to No")
        try:
            tab = dlg.TabItemControl(Name="Track parameter")
            if tab.Exists(1):
                try: tab.GetSelectionItemPattern().Select()
                except Exception: tab.Click()
                time.sleep(0.2)
        except Exception:
            pass
        combo = find_stat_combo(dlg)
        ok = set_combo(combo, target) if combo else False
        try: now = combo.GetValuePattern().Value
        except Exception: now = "?"
        print("    row %d: stat -> %s (ok=%s)" % (i, now, ok))
        okb = dlg.ButtonControl(Name="OK")
        if okb.Exists(1) and not invoke(okb):
            okb.Click()
        time.sleep(0.3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stat1", default="Maximum", help="stat for rows 1-3")
    ap.add_argument("--stat2", default="Average [Q]", help="stat for rows 4-6")
    ap.add_argument("--skip-data", action="store_true")
    args = ap.parse_args()
    stat_map = {1: args.stat1, 2: args.stat1, 3: args.stat1,
                4: args.stat2, 5: args.stat2, 6: args.stat2}

    if not args.skip_data:
        setup_data()
    set_stats(stat_map)
    graphic_output()
    print("Done. Diagram 1 = rows1-3 (%s), Diagram 2 = rows4-6 (%s)." % (args.stat1, args.stat2))


if __name__ == "__main__":
    main()
