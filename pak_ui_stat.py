# -*- coding: utf-8 -*-
"""Set the Track-parameter 'Stat. parameter' of an open PAK "Data definition"
dialog via Windows UI Automation (no pixel clicks), then optionally click OK.

The Stat. parameter combo is the first ComboBox in the 'Additional Calculations'
group; its item list contains Average [lin], Average [Q], Maximum, Minimum, ...

Requires: pip install uiautomation

Examples:
  python pak_ui_stat.py --value Maximum --ok
  python pak_ui_stat.py --row 4 --value "Average [Q]" --ok
  python pak_ui_stat.py --value Maximum            # set, leave dialog open
"""
import sys, argparse
try:
    import uiautomation as auto
except Exception:
    print("ERROR: pip install uiautomation"); sys.exit(1)

STAT_VALUES = {"Average [lin]", "Average [Q]", "Maximum", "Minimum",
               "dB Average [lin]", "dB Average [Q]", "-"}


def find_dialog(row=None):
    root = auto.GetRootControl()
    want = "Data definition to No %s" % row if row else "Data definition to No"
    for w in root.GetChildren():
        name = ""
        try:
            name = w.Name or ""
        except Exception:
            pass
        if want.lower() in name.lower():
            return w, name
    return None, None


def find_stat_combo(win):
    """Return the Stat. parameter combo = topmost 'Additional Calculations' combo
    whose item set includes 'Maximum'."""
    combos = []
    for c in win.GetChildren(lambda ctrl, d: True) if False else []:
        pass
    # walk manually
    stack = [win]
    found = []
    while stack:
        node = stack.pop()
        try:
            if node.ControlTypeName == "ComboBoxControl" and (node.Name or "") == "Additional Calculations":
                found.append(node)
        except Exception:
            pass
        try:
            stack.extend(node.GetChildren())
        except Exception:
            pass
    if not found:
        return None
    # pick the one whose current value is a stat value, else the topmost
    def top(c):
        try:
            return c.BoundingRectangle.top
        except Exception:
            return 0
    stat = None
    for c in found:
        try:
            v = c.GetValuePattern().Value
        except Exception:
            v = ""
        if v in STAT_VALUES and v != "-":
            stat = c; break
    if stat is None:
        found.sort(key=top)
        stat = found[0]
    return stat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--row", help="target 'Data definition to No <row>' window")
    ap.add_argument("--value", required=True, help="Maximum | Average [Q] | Average [lin] | Minimum ...")
    ap.add_argument("--ok", action="store_true", help="click OK after setting")
    args = ap.parse_args()

    win, title = find_dialog(args.row)
    if not win:
        print("No 'Data definition' dialog found. Open the row's dialog first.")
        return
    print("Dialog:", title)
    win.SetActive()

    combo = find_stat_combo(win)
    if not combo:
        print("Stat. parameter combo not found.")
        return
    try:
        cur = combo.GetValuePattern().Value
    except Exception:
        cur = "?"
    print("Stat. parameter current =", cur)

    ok = False
    # 1) try ValuePattern
    try:
        combo.GetValuePattern().SetValue(args.value)
        ok = True
    except Exception as e:
        print("ValuePattern.SetValue failed:", e)
    # 2) fall back to Select (expand + pick item)
    if not ok:
        try:
            combo.Select(args.value)
            ok = True
        except Exception as e:
            print("Select failed:", e)

    try:
        newv = combo.GetValuePattern().Value
    except Exception:
        newv = "?"
    print("Stat. parameter now =", newv, "(set ok=%s)" % ok)

    if args.ok:
        okbtn = win.ButtonControl(Name="OK")
        if okbtn.Exists(1):
            okbtn.Click()
            print("Clicked OK.")
        else:
            print("OK button not found.")


if __name__ == "__main__":
    main()
