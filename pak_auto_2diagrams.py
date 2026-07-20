# -*- coding: utf-8 -*-
"""Full UI-Automation flow: set per-row Track 'Stat. parameter' then Graphic Output.

Default: rows 1-3 -> Maximum, rows 4-6 -> Average [Q], then click Graphic Output,
producing 2 diagrams (Diagram 1 = Max curves, Diagram 2 = Average curves).

Relies on facts confirmed by the scans:
  - Grid window title: 'Graphic Definition'
  - Each populated row's Data Definition cell is a ButtonControl whose Name
    contains 'Pos.' (e.g. 'APS Pos. Gear Lever +X-m/s^2 (2D)'); double-click opens
    the 'Data definition to No N' dialog.
  - In that dialog: TabItem 'Track parameter'; the Stat. parameter combo is the
    first 'Additional Calculations' ComboBox (items: Average [Q], Maximum, ...).
  - Buttons 'OK' (dialog) and 'Graphic Output' (grid window).

Requires: pip install uiautomation
Usage:
  python pak_auto_2diagrams.py
  python pak_auto_2diagrams.py --map "1=Maximum,2=Maximum,3=Maximum,4=Average [Q],5=Average [Q],6=Average [Q]"
  python pak_auto_2diagrams.py --no-output      # set stats but don't click Graphic Output
"""
import sys, time, argparse
try:
    import uiautomation as auto
except Exception:
    print("ERROR: pip install uiautomation"); sys.exit(1)

STAT_VALUES = {"Average [lin]", "Average [Q]", "Maximum", "Minimum",
               "dB Average [lin]", "dB Average [Q]", "-"}


def find_window(substr):
    for w in auto.GetRootControl().GetChildren():
        try:
            if substr.lower() in (w.Name or "").lower():
                return w
        except Exception:
            pass
    return None


def data_def_cells(grid):
    """Return the row Data-Definition ButtonControls, sorted top->bottom (row 1..N)."""
    cells = []
    stack = [grid]
    while stack:
        n = stack.pop()
        try:
            if n.ControlTypeName == "ButtonControl":
                nm = n.Name or ""
                if " Pos." in nm and ("(2D)" in nm or "(3D)" in nm):
                    cells.append(n)
        except Exception:
            pass
        try:
            stack.extend(n.GetChildren())
        except Exception:
            pass
    def top(c):
        try:
            return c.BoundingRectangle.top
        except Exception:
            return 0
    # de-dup by rectangle top
    uniq = {}
    for c in cells:
        uniq[top(c)] = c
    return [uniq[k] for k in sorted(uniq)]


def find_stat_combo(win):
    found = []
    stack = [win]
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
    if not found:
        return None
    for c in found:
        try:
            if c.GetValuePattern().Value in STAT_VALUES:
                # prefer the topmost stat combo
                pass
        except Exception:
            pass
    found.sort(key=lambda c: (c.BoundingRectangle.top if c.BoundingRectangle else 0))
    return found[0]


def set_combo(combo, value):
    try:
        combo.GetValuePattern().SetValue(value)
        if combo.GetValuePattern().Value == value:
            return True
    except Exception:
        pass
    try:
        combo.Select(value)
        return True
    except Exception as e:
        print("   Select failed:", e)
        return False


def parse_map(s):
    m = {}
    for part in s.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            m[int(k.strip())] = v.strip()
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="1=Maximum,2=Maximum,3=Maximum,4=Average [Q],5=Average [Q],6=Average [Q]")
    ap.add_argument("--no-output", action="store_true")
    args = ap.parse_args()
    stat_map = parse_map(args.map)

    grid = find_window("Graphic Definition")
    if not grid:
        print("Graphic Definition window not found."); return
    grid.SetActive(); time.sleep(0.3)

    cells = data_def_cells(grid)
    print("Found %d data-definition rows." % len(cells))
    if not cells:
        return

    for i, cell in enumerate(cells, start=1):
        if i not in stat_map:
            continue
        target = stat_map[i]
        print("\n--- Row %d -> Stat.parameter '%s' ---" % (i, target))
        try:
            cell.DoubleClick()
        except Exception as e:
            print("   double-click failed:", e); continue
        time.sleep(0.6)
        dlg = find_window("Data definition to No")
        if not dlg:
            print("   dialog did not open."); continue
        # select Track parameter tab
        try:
            tab = dlg.TabItemControl(Name="Track parameter")
            if tab.Exists(1):
                tab.Select()
                time.sleep(0.2)
        except Exception as e:
            print("   tab select warn:", e)
        combo = find_stat_combo(dlg)
        if not combo:
            print("   stat combo not found."); 
        else:
            try:
                cur = combo.GetValuePattern().Value
            except Exception:
                cur = "?"
            ok = set_combo(combo, target)
            try:
                now = combo.GetValuePattern().Value
            except Exception:
                now = "?"
            print("   stat: %s -> %s (ok=%s)" % (cur, now, ok))
        # OK
        okb = dlg.ButtonControl(Name="OK")
        if okb.Exists(1):
            okb.Click()
            print("   OK clicked.")
        else:
            print("   OK not found; pressing Enter.")
            dlg.SendKeys("{Enter}")
        time.sleep(0.4)

    if not args.no_output:
        grid.SetActive(); time.sleep(0.2)
        gob = grid.ButtonControl(Name="Graphic Output")
        if gob.Exists(1):
            gob.Click()
            print("\nGraphic Output clicked.")
        else:
            print("\nGraphic Output button not found.")
    print("\nDone.")


if __name__ == "__main__":
    main()
