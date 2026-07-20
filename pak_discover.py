"""PAK COM discovery helper.

Run this ONCE on the Windows PC where PAK is installed (with PAK open, ideally
with the Graphic Definition window shown). It finds the correct COM ProgID and
prints the exact property/method names the MCP server needs, then tells you which
environment variables to set.

    python pak_discover.py

No arguments needed. It does not change anything in PAK; it only reads.
"""

from __future__ import annotations

import winreg
import win32com.client as win32


def find_progids():
    """Scan the registry for ProgIDs that look like PAK's COM server."""
    found = []
    root = winreg.HKEY_CLASSES_ROOT
    try:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            low = name.lower()
            if "." in name and ("pak" in low or "muller" in low or "bbm" in low):
                found.append(name)
    except Exception:
        pass
    guesses = ["Pak.Application", "PakLib.Application", "PAK.Application"]
    ordered = [g for g in guesses if g not in found] + found
    return ordered


def connect(progids):
    for pid in progids:
        for how in ("GetActiveObject", "Dispatch"):
            try:
                app = getattr(win32, how)(pid)
                print("[OK] Connected via %s('%s')" % (how, pid))
                return app, pid
            except Exception:
                continue
    return None, None


def members(obj):
    try:
        return sorted(m for m in dir(obj) if not m.startswith("_"))
    except Exception:
        return []


def find_attr(obj, name_candidates, keyword_contains):
    """Return matching member names by exact candidate or keyword substring."""
    ms = members(obj)
    exact = [c for c in name_candidates if c in ms]
    fuzzy = [m for m in ms if any(k in m.lower() for k in keyword_contains)]
    return exact, sorted(set(fuzzy) - set(exact))


def get_graphdef(app):
    for attr in ("GraphDef", "GraphicDefinition", "Graphdef"):
        gd = getattr(app, attr, None)
        if gd is not None:
            print("[OK] GraphDef found on app.%s" % attr)
            return gd, attr
    print("[!!] Could not find GraphDef on the app object.")
    print("     app members:", members(app))
    return None, None


def main():
    print("=== PAK COM discovery ===")
    print("")
    progids = find_progids()
    print("ProgID candidates to try:", progids)
    print("")

    app, pid = connect(progids)
    if app is None:
        print("[!!] Could not connect to PAK. Make sure PAK is running, then retry.")
        print("     If you know the ProgID, note it and set PAK_PROGID manually.")
        return

    print("")
    print(">>> PAK_PROGID = " + str(pid))
    print("")

    gd, _ = get_graphdef(app)
    if gd is None:
        return

    # Graphic Output method.
    # NOTE: gd.Graphic often raises "Please plot graphic first" until a plot
    # exists, so the output trigger is usually a method on GraphDef itself.
    print("")
    print("--- Graphic Output ---")
    print("GraphDef members:", members(gd))
    exact, fuzzy = find_attr(
        gd,
        ["GraphicOutput", "Output", "Plot", "Print", "Show", "Execute", "Draw"],
        ["output", "plot", "print", "show", "exec", "render", "draw", "graphic"],
    )
    print("Likely output methods on GraphDef:", exact + fuzzy)
    if exact + fuzzy:
        print(">>> PAK_OUTPUT_METHODS = " + ",".join(exact + fuzzy))

    try:
        graphic = gd.Graphic
        print("GraphDef.Graphic members:", members(graphic))
    except Exception as exc:
        print("(GraphDef.Graphic not readable yet: %s)" % exc)

    # Row / Datatype introspection (row 1)
    try:
        item = gd.Item(1)
        print("")
        print("--- Item(1) members ---")
        print(members(item))
        dt = getattr(item, "Datatype", None)
        if dt is not None:
            exact, fuzzy = find_attr(
                dt,
                ["Freqweight", "Weighting", "Fweight", "FreqWeighting"],
                ["weight", "fweight", "abc"],
            )
            print("")
            print("--- Display/Filter frequency weighting ---")
            print("Datatype members:", members(dt))
            print("Likely weighting props:", exact + fuzzy)
            if exact + fuzzy:
                print(">>> PAK_WEIGHT_PROPS = " + ",".join(exact + fuzzy))
    except Exception as exc:
        print("")
        print("[!!] Could not read Item(1)/Datatype: %s" % exc)

    print("")
    print("=== Done. Set the >>> variables shown above before running the server. ===")


if __name__ == "__main__":
    main()
