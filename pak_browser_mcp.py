# -*- coding: utf-8 -*-
"""PAK Browser MCP server (server #2).

Reads the current PAK project and its data list (Project -> test -> subtitle) via
the PAK Browser COM object + filesystem enumeration of DestDataPath. Same Tcl COM
bridge as the Graphic Definition server.

Channel info for a stored subtitle is read straight from the subtitle folder
(no COM, no blocking popups). Two storage formats are supported:
  * theader.xml            (newer measurements, e.g. ExampleMOI)
  * MeasSetup/ text files  (MessSetup format, e.g. ExampleASD)
Both reproduce PAK's "Channel Overview" table (Nr / Type / Label / Dir / Quantity).

Data model:  Project (ProjectFolder) / test / subtitle
  e.g.  PAKLLM / ExampleMOI / Acceleration_Run_01

Config (env):
    PAK_TCL_INIT  path to PAK's Tcl init file (default PAK 6.4 location)
"""
import os
import re
import xml.etree.ElementTree as ET
import tkinter as tk
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("PAK-Browser")

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)

_tcl = tk.Tcl()
_sourced = False


def _ev(cmd):
    return _tcl.eval(cmd)


def _ensure_sourced():
    global _sourced
    if not _sourced:
        _ev("source {%s}" % PAK_TCL_INIT)
        _sourced = True
    _ev("set pak_application")


def _reset():
    for v in ["browser", "reference"]:
        try:
            _ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v, v, v))
        except Exception:
            pass


def _open_browser():
    _ensure_sourced()
    _reset()
    _ev("set reference [createobject $pak_application]")
    _ev("set browser [$reference Browser]")


def _close_browser():
    for v in ["browser", "reference"]:
        try:
            _ev("catch {release $%s}; unset %s" % (v, v))
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Channel parsing -- pure filesystem, no COM.
# Format A: theader.xml  (ExampleMOI)
# Format B: MeasSetup/    (ExampleASD, MessSetup text files)
# --------------------------------------------------------------------------- #
_DE_EN_QUANTITY = {
    "Schalldruck": "Sound Pressure",
    "Beschleunigung": "Acceleration",
    "Vibrat. Beschleunigung": "Vibrat. Acceleration",
    "Drehzahl": "Rotational Speed",
    "Spannung": "Voltage",
    "El. Spannung": "Voltage",
    "Temperatur": "Temperature",
    "Kraft": "Force",
    "Weg": "Displacement",
    "Geschwindigkeit": "Velocity",
    "Ordnung": "Order",
    "Frequenz": "Frequency",
    "Winkel": "Angle",
    "Dehnung": "Strain",
    "Druck": "Pressure",
    "Undefiniert": "Undefined",
}


def _en_quantity(q):
    """Return English quantity name. Translates German terms; leaves English/other
    values (e.g. 'Rotational Speed') unchanged."""
    if not q:
        return q
    return _DE_EN_QUANTITY.get(q.strip(), q.strip())


def _localname(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(elem, name):
    for c in elem:
        if _localname(c.tag) == name:
            return (c.text or "").strip()
    return ""


def _child_elem(elem, name):
    for c in elem:
        if _localname(c.tag) == name:
            return c
    return None


def _direction_from_xyz(pos):
    """+X/-X/+Y/-Y/+Z/-Z from xdir/ydir/zdir unit vector; 'S' if none."""
    if pos is None:
        return "S"

    def val(tag):
        try:
            return float(_child_text(pos, tag) or 0)
        except (ValueError, TypeError):
            return 0.0

    for axis, v in (("X", val("xdir")), ("Y", val("ydir")), ("Z", val("zdir"))):
        if abs(v) > 0.5:
            return ("+" if v > 0 else "-") + axis
    return "S"


def _parse_channels_theader(theader_path):
    """theader.xml -> list of channels (ExampleMOI-style)."""
    with open(theader_path, "rb") as fh:
        raw = fh.read()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(raw.decode("mbcs", "replace").encode("utf-8"))

    channels = []
    seen = set()
    for cg in root.iter():
        if _localname(cg.tag) != "channel_group":
            continue
        if _child_text(cg, "type") != "sampling_group":
            continue  # skip overload/level/compressed representations
        group_name = _child_text(cg, "name")
        for ch in cg.iter():
            if _localname(ch.tag) not in ("normal", "amplitude"):
                continue
            pos = _child_elem(ch, "position")
            if pos is None:
                continue
            nr = _child_text(ch, "id")
            name = _child_text(ch, "name")
            key = (group_name, nr, name)
            if key in seen:
                continue
            seen.add(key)
            channels.append({
                "nr": int(nr) if nr.isdigit() else nr,
                "type": _child_text(pos, "mptype") or "",
                "label": _child_text(pos, "label") or "",
                "direction": _direction_from_xyz(pos),
                "quantity": _en_quantity(_child_text(ch, "quantity")),
                "name": name,
                "mptext": _child_text(pos, "mptext") or "",
                "group": group_name,
                "active": True,
            })
    channels.sort(key=lambda c: (c["nr"] if isinstance(c["nr"], int) else 9999))
    return channels


def _parse_messsetup_file(path):
    """Parse a PAK MessSetup text file into a flat {key: value} dict."""
    d = {}
    if not os.path.isfile(path):
        return d
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("mbcs", "replace")
    for ln in text.splitlines():
        s = ln.strip()
        if (not s or s.startswith("#") or s.startswith("<")
                or s.endswith("{") or s == "}"):
            continue
        parts = s.split(None, 1)
        d[parts[0]] = parts[1].strip() if len(parts) == 2 else ""
    return d


def _indexed(d, prefix):
    """Return {i: value} for keys like PREFIX<i> (i = integer)."""
    out = {}
    pat = re.compile(r"^%s(\d+)$" % re.escape(prefix))
    for k, v in d.items():
        m = pat.match(k)
        if m:
            out[int(m.group(1))] = v
    return out


def _parse_channels_messsetup(meas_dir):
    """MeasSetup/ folder -> list of channels (ExampleASD-style MessSetup)."""
    chanpos = _parse_messsetup_file(os.path.join(meas_dir, "ChanPos"))
    chanset = _parse_messsetup_file(os.path.join(meas_dir, "ChanSetting"))
    quant = _parse_messsetup_file(os.path.join(meas_dir, "Quantity"))
    setup = _parse_messsetup_file(os.path.join(meas_dir, "Setup"))

    names = _indexed(quant, "NAME")               # local quantity-name table
    pos = _indexed(chanpos, "POS")                # channel position name (CH1..)
    mptype = _indexed(chanpos, "MPTYPE")
    mptext = _indexed(chanpos, "MPTEXT")
    direction = _indexed(chanpos, "DIRECTION")
    active = _indexed(chanset, "ACTIVE")
    localq = _indexed(chanset, "LOCAL_QUANTITY_ID")
    measmode = _indexed(chanset, "MEASMODE")
    group = setup.get("GRP_ONE_NAME", "")

    channels = []
    for i in sorted(pos):
        lq = localq.get(i, "")
        quantity = _en_quantity(names.get(int(lq), "") if lq.isdigit() else "")
        channels.append({
            "nr": i + 1,
            "type": mptype.get(i, "") or "",
            "label": pos.get(i, "") or "",
            "direction": direction.get(i, "") or "S",
            "quantity": quantity,
            "name": pos.get(i, "") or "",
            "mptext": mptext.get(i, "") or "",
            "measmode": measmode.get(i, "") or "",
            "group": group,
            "active": active.get(i, "").upper() == "ON",
        })
    return channels


def _resolve_subtitle_folder(subtitle, base):
    """Resolve a subtitle spec to a folder path.

    Accepts an absolute folder path, or "test/subtitle" (optionally with a
    trailing " [CP]") relative to the project base (DestDataPath).
    """
    s = subtitle.strip()
    if "[" in s:
        s = s[: s.index("[")].strip()
    s = s.rstrip("/\\")
    if os.path.isdir(s):
        return s
    if base:
        return os.path.join(base, *s.replace("\\", "/").split("/"))
    return s


# --------------------------------------------------------------------------- #
@mcp.tool()
def get_current_project() -> dict:
    """Return the current PAK project name and key paths (Browser object)."""
    try:
        _open_browser()
        info = {
            "project": _ev("$browser ProjectFolder"),
            "data_path": _ev("$browser DataPath"),
            "dest_data_path": _ev("$browser DestDataPath"),
        }
        try:
            info["backup_path"] = _ev("$browser BackupPath")
            info["example_path"] = _ev("$browser ExamplePath")
        except Exception:
            pass
        return {"ok": True, **info}
    finally:
        _close_browser()
        _reset()


@mcp.tool()
def list_project_data(project_path: str = "") -> dict:
    """List the current project's data as Project -> test -> subtitle.

    Enumerates DestDataPath (or an explicit project_path). Each top-level folder is
    a 'test'; each folder inside it is a 'subtitle'. The measurement name used by
    the Graphic Definition server is  "<test>/<subtitle>".

    Args:
        project_path: optional path to enumerate; defaults to Browser DestDataPath.
    """
    try:
        _open_browser()
        base = project_path or _ev("$browser DestDataPath")
        project = _ev("$browser ProjectFolder")
    finally:
        _close_browser()
        _reset()

    if not base or not os.path.isdir(base):
        return {"ok": False, "error": "path not found: %r" % base, "project": project}

    tests = {}
    total = 0
    for test in sorted(os.listdir(base)):
        tp = os.path.join(base, test)
        if not os.path.isdir(tp):
            continue
        subs = [s for s in sorted(os.listdir(tp)) if os.path.isdir(os.path.join(tp, s))]
        tests[test] = subs
        total += len(subs)
    measurements = [f"{t}/{s}" for t, subs in tests.items() for s in subs]
    return {"ok": True, "project": project, "path": base,
            "tests": tests, "measurements": measurements,
            "test_count": len(tests), "subtitle_count": total}


@mcp.tool()
def list_last_measurements() -> dict:
    """Return the paths of the last measurements (Browser.LastMeasurements)."""
    try:
        _open_browser()
        _ev("set lm [$browser LastMeasurements]")
        n = int(_ev("$lm Count"))
        items = []
        for i in range(n):
            try:
                items.append(_ev("[$lm Item %d] Path" % i))
            except Exception:
                pass
        _ev("catch {release $lm}; unset lm")
        return {"ok": True, "count": n, "paths": items}
    finally:
        _close_browser()
        _reset()


@mcp.tool()
def get_channels(subtitle: str, project_path: str = "",
                 include_inactive: bool = False) -> dict:
    """Return a stored subtitle's channel list (PAK "Channel Overview" table).

    Reads the subtitle folder directly from disk -- no COM, no blocking popups.
    Two storage formats are handled automatically:
      * theader.xml           (e.g. ExampleMOI) -> all listed channels
      * MeasSetup/ text files  (e.g. ExampleASD) -> configured channels; by
        default only ACTIVE ones (set include_inactive=True for all 16).
    Each channel reports Nr / Type / Label / Direction / Quantity, as in PAK's
    Channel Overview.

    Args:
        subtitle: "test/subtitle" (e.g. "ExampleMOI/Acceleration_Run_01"; a
            trailing " [CP]" is ignored) or an absolute path to the subtitle folder.
        project_path: optional project base (DestDataPath). If omitted, read from
            the Browser object.
        include_inactive: for MessSetup subtitles, include inactive channels too.

    Returns keys: ok, subtitle, folder, format, count, channels[]. Each channel has
    nr, type, label, direction, quantity, name, mptext, group, active.
    """
    base = project_path
    if not base and not os.path.isabs(subtitle.strip().rstrip("/\\")):
        try:
            _open_browser()
            base = _ev("$browser DestDataPath")
        except Exception:
            base = ""
        finally:
            _close_browser()
            _reset()

    folder = _resolve_subtitle_folder(subtitle, base)
    if not os.path.isdir(folder):
        return {"ok": False, "error": "subtitle folder not found",
                "subtitle": subtitle, "folder": folder}

    theader = os.path.join(folder, "theader.xml")
    meas_dir = os.path.join(folder, "MeasSetup")
    try:
        if os.path.isfile(theader):
            fmt = "theader.xml"
            channels = _parse_channels_theader(theader)
        elif os.path.isdir(meas_dir):
            fmt = "MeasSetup"
            channels = _parse_channels_messsetup(meas_dir)
            if not include_inactive:
                channels = [c for c in channels if c.get("active")]
        else:
            return {"ok": False,
                    "error": "no theader.xml or MeasSetup/ in subtitle folder",
                    "subtitle": subtitle, "folder": folder}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "parse failed: %s" % exc,
                "subtitle": subtitle, "folder": folder}

    return {"ok": True, "subtitle": subtitle, "folder": folder,
            "format": fmt, "count": len(channels), "channels": channels}


if __name__ == "__main__":
    mcp.run()
