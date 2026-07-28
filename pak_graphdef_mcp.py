# -*- coding: utf-8 -*-
"""PAK Graphic Definition MCP server (Tcl COM bridge).

Automates the Mueller-BBM PAK "Graphic Definition" window and runs Graphic
Output. Drives PAK through its official Tcl COM bridge (the same mechanism the
existing PAK MCP servers use) rather than raw win32com, because PAK's row
objects require PAK's createobject/release reference protocol.

Structure (matches the UI):
    GraphDef (grid)
      Item(row-1)                      <- one grid row (0-based in COM!)
        .Active / .Diag / .Curve / .Datafile
        .Datentyp  (the "Data Definition" detail window)
            SetChanpos <pos> <dir> <quant>   (channel / direction / quantity)
            Mdtype <measurement data type>   (e.g. Throughput)
            Pdtype <graphic data type>       (e.g. APS)
            Srate  <sampling rate>
            Tp2det_fweight / Tp2oct_fweight  (A/B/C/lin frequency weighting)
        .TrackingParams
            SetChanposTrack {} {} <quant>    (e.g. Time)
            Start <Min|Max|value> / Stop
      Graphicoutput                    <- runs Graphic Output

Config (environment variables):
    PAK_TCL_INIT   Path to PAK's Tcl init file. Default:
                   C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl
    PAK_WEIGHT_PROPS  Comma-separated weighting property names to try, in order.
                      Default: Tp2det_fweight,Tp2oct_fweight
"""

import os
import sys
import json
import tkinter as tk

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("PAK")

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)
WEIGHT_PROPS = [
    p.strip()
    for p in os.environ.get("PAK_WEIGHT_PROPS", "Tp2det_fweight,Tp2oct_fweight").split(",")
    if p.strip()
]

# Remembers the weighting property that last worked, so subsequent rows try it
# first instead of re-attempting (and failing on) earlier candidates every time.
_WEIGHT_PROP_CACHE = None

# Track "Stat. parameter" -> exact PAK COM token (spacing matters!)
STAT_MAP = {
    "-": "-", "none": "-", "None": "-", "Not use": "-", "3D": "-",
    "Average [lin]": "Mittelwert   [lin]",
    "Average [Q]": "Mittelwert   [  Q]",
    "Standard dev. [lin]": "Std.abw.     [lin]",
    "Standard dev. [Q]": "Std.abw.     [  Q]",
    "Std.dev.band [lin]": "Std.abw.band [lin]",
    "Std.dev.band [Q]": "Std.abw.band [  Q]",
    "Maximum": "Maximum",
    "Minimum": "Minimum",
    "dB Average [lin]": "Mittelwert dB [lin]",
    "dB Average [Q]": "Mittelwert dB [  Q]",
    "dB Standard dev. [lin]": "Std.abw.   dB [lin]",
    "dB Standard dev. [Q]": "Std.abw.   dB [  Q]",
    "dB Std.dev.band [lin]": "Std.abw.band dB [lin]",
    "dB Std.dev.band [Q]": "Std.abw.band dB [  Q]",
    "Envelope Curve": "Huellkurve",
    "Percentile shape": "Perzentilverlauf",
}


_tcl = tk.Tcl()
_sourced = False


# --------------------------------------------------------------------------- #
# Low-level Tcl helpers
# --------------------------------------------------------------------------- #
def _ev(cmd):
    return _tcl.eval(cmd)


def _brace(value):
    """Quote a value for Tcl as a single {..} token."""
    s = "" if value is None else str(value)
    return "{%s}" % s


def _cp_suffix(name):
    """PAK's 'Name of Measurement' expects the subtitle followed by a space and
    the ' [CP]' (Current Project) tag. Append it automatically unless the caller
    already supplied a bracket tag (e.g. '... [CP]')."""
    s = "" if name is None else str(name).strip()
    if not s:
        return s
    if s.endswith("]"):        # already tagged, e.g. "... [CP]"
        return s
    return s + " [CP]"


def _ensure_sourced():
    global _sourced
    if not _sourced:
        _ev("source {%s}" % PAK_TCL_INIT)
        _sourced = True
    # confirm the application id is defined
    _ev("set pak_application")


def _reset():
    """Release any lingering COM handles from a previous (possibly aborted) call."""
    for v in ["dt", "tp", "it", "gd", "reference"]:
        try:
            _ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v, v, v))
        except Exception:
            pass


def _open_gd(visible=True):
    """Create reference + GraphDef handles. Caller must _close_gd() afterwards."""
    _ensure_sourced()
    _reset()
    _ev("set reference [createobject $pak_application]")
    _ev("set gd [$reference GraphDef]")
    if visible:
        _ev("$gd Visible 1")


def _close_gd():
    for v in ["gd", "reference"]:
        try:
            _ev("catch {release $%s}; unset %s" % (v, v))
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Row-level building block (used by the granular tools and configure_row)
# --------------------------------------------------------------------------- #
def _emit_sound_fweight(quantity, weighting=None, sound_weighting="A", steps=None):
    """Apply frequency weighting via Item.DarstFilter.Fweight -- the WRITABLE + EFFECTIVE
    path for APS / Order APS / Order complex spectra (Datentyp.Tp2*_fweight is a NO-OP for
    these; verified). Sound is ALWAYS A-weighted: when no explicit `weighting` is given,
    `sound_weighting` (default 'A') is auto-applied to Sound Pressure channels, while
    vibration / other quantities stay linear. Assumes $it exists and $dt has already been
    released (DarstFilter is an Item sub-object). Returns the weighting actually applied."""
    _wt = weighting
    if not _wt:
        _q = (quantity or "").lower()
        if sound_weighting and ("sound" in _q or "pressure" in _q):
            _wt = sound_weighting
    if _wt and str(_wt).lower() != "lin":
        _ev("set df [$it DarstFilter]")
        try:
            _ev("$df Fweight %s" % _brace(_wt))
            if steps is not None:
                steps["weighting"] = _wt
        except Exception:
            pass
        _ev("catch {release $df}; unset df")
    else:
        if steps is not None:
            steps["weighting"] = "lin"
    return _wt


def _apply_row(
    row,
    active=None,
    diagram=None,
    curve=None,
    measurement=None,
    position=None,
    direction=None,
    quantity=None,
    measurement_data_type=None,
    graphic_data_type=None,
    sampling_rate=None,
    blocksize=None,
    track_quantity=None,
    track_position=None,
    track_direction=None,
    track_start=None,
    track_stop=None,
    weighting=None,
    stat_parameter=None,
    x_from=None,
    x_to=None,
    x_type=None,
    y_type=None,
    y_from=None,
    y_to=None,
):
    """Configure one row on an already-open GraphDef ($gd). Row is 1-based.

    For APS / Octave spectra the analysis is fixed to Sampling rate 32768 and
    FFT Blocksize 16384 (Tp2spec_blocksize) unless the caller passes an explicit
    sampling_rate / blocksize override.
    """
    steps = {}
    # Fixed defaults for spectrum analyses (APS, Octave).
    _gdt = (graphic_data_type or "").upper()
    _is_spectrum = ("APS" in _gdt) or ("OCT" in _gdt)
    if _is_spectrum:
        if sampling_rate is None:
            sampling_rate = "32768"
        if blocksize is None:
            blocksize = "16384"
    idx = row - 1  # COM Item is 0-based
    _ev("set it [$gd Item %d]" % idx)

    if active is not None:
        _ev("$it Active %d" % (1 if active else 0))
        steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram))
        steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve))
        steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement))
        steps["measurement"] = measurement

    # Data definition detail (Datentyp)
    need_dt = any(v is not None for v in (position, quantity, measurement_data_type,
                                          graphic_data_type, sampling_rate, blocksize,
                                          weighting))
    if need_dt:
        _ev("set dt [$it Datentyp]")
        if quantity:
            _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(direction), _brace(quantity)))
            steps["channel"] = {"position": position, "direction": direction, "quantity": quantity}
        if measurement_data_type:
            _ev("$dt Mdtype %s" % _brace(measurement_data_type))
            steps["measurement_data_type"] = measurement_data_type
        if graphic_data_type:
            _ev("$dt Pdtype %s" % _brace(graphic_data_type))
            steps["graphic_data_type"] = graphic_data_type
        if sampling_rate:
            _ev("$dt Srate %s" % _brace(sampling_rate))
            steps["sampling_rate"] = sampling_rate
        if blocksize:
            _ev("$dt Tp2spec_blocksize %s" % _brace(blocksize))
            steps["blocksize"] = blocksize
        if weighting:
            global _WEIGHT_PROP_CACHE
            used = None
            last_err = None
            # Try the previously-successful property first, then the rest. Avoids
            # re-attempting candidates that always fail for this data type
            # (e.g. Tp2det_fweight on Octave rows) on every single row.
            ordered = list(WEIGHT_PROPS)
            if _WEIGHT_PROP_CACHE in ordered:
                ordered.remove(_WEIGHT_PROP_CACHE)
                ordered.insert(0, _WEIGHT_PROP_CACHE)
            for prop in ordered:
                try:
                    _ev("$dt %s %s" % (prop, _brace(weighting)))
                    used = prop
                    _WEIGHT_PROP_CACHE = prop
                    break
                except Exception as exc:
                    last_err = exc
            if used:
                steps["weighting"] = {"value": weighting, "property": used}
            else:
                steps["weighting_error"] = str(last_err)
        _ev("catch {release $dt}; unset dt")
        # Sound is ALWAYS A-weighted: for APS/Octave spectra apply the EFFECTIVE
        # weighting path (Item.DarstFilter.Fweight). Datentyp.Tp2*_fweight above is a
        # no-op for these, so this is what actually makes the axis dB(A). Auto-applies
        # A to Sound Pressure; explicit `weighting` (incl. "lin") is honoured.
        if _is_spectrum:
            _emit_sound_fweight(quantity, weighting, "A", steps)

    # Track parameter
    if (track_quantity is not None or track_position is not None
            or track_direction is not None or track_start is not None
            or track_stop is not None or stat_parameter is not None):
        _ev("set tp [$it TrackingParams]")
        tq = track_quantity or "Time"
        _tstart = track_start if track_start is not None else "Min"
        _tstop = track_stop if track_stop is not None else "Max"
        if track_position:
            # Channel track (e.g. Distance in exterior/pass-by). PAK requires a
            # position label for a channel track, so the empty-position form fails
            # with "requires a position label". Pass position/direction/quantity
            # explicitly (as get_channels reports them, e.g. Distance / S /
            # "Cart. coord.x").
            _tdir = track_direction if track_direction is not None else "S"
            _ev("$tp SetChanposTrack %s %s %s"
                % (_brace(track_position), _brace(_tdir), _brace(tq)))
            steps["track"] = {"position": track_position, "direction": _tdir,
                              "quantity": tq, "start": _tstart, "stop": _tstop}
        else:
            _ev("$tp SetChanposTrack {} {} %s" % _brace(tq))
            steps["track"] = {"quantity": tq, "start": _tstart, "stop": _tstop}
        _ev("$tp Start %s" % _brace(_tstart))
        _ev("$tp Stop %s" % _brace(_tstop))
        if stat_parameter is not None:
            token = STAT_MAP.get(stat_parameter, stat_parameter)
            _ev("$tp Stats %s" % _brace(token))
            steps["stat_parameter"] = {"value": stat_parameter, "token": token}
        _ev("catch {release $tp}; unset tp")

    # Axis scaling (Scale Definition -> Scaling of axes).
    #   Item.SkalenDefinition.AchsenSkalierung
    #   slot1_ = X axis (frequency), slot2_ = Y axis (level)
    #   Type<k>_ = lin|log|dB ; Von<k>_/Bis<k>_ = from/to ; "OFF" = Auto
    if any(v is not None for v in (x_from, x_to, x_type, y_type, y_from, y_to)):
        _ev("set sd [$it SkalenDefinition]")
        _ev("set ax [$sd AchsenSkalierung]")
        axinfo = {}
        # X (frequency) axis -- slot 1
        if x_from is not None or x_to is not None or x_type is not None:
            _ev("$ax Aktiv1_ 1")
            _ev("$ax Type1_ %s" % _brace(x_type or "lin"))
            _ev("$ax Von1_ %s" % _brace(x_from if x_from is not None else 0))
            _ev("$ax Bis1_ %s" % _brace(x_to if x_to is not None else "OFF"))
            axinfo["x"] = {"type": x_type or "lin",
                           "from": x_from if x_from is not None else 0,
                           "to": x_to if x_to is not None else "OFF"}
        # Y (level) axis -- slot 2 ; default Auto (OFF/OFF)
        _ev("$ax Aktiv2_ 1")
        _ev("$ax Type2_ %s" % _brace(y_type or "dB"))
        _ev("$ax Von2_ %s" % _brace(y_from if y_from is not None else "OFF"))
        _ev("$ax Bis2_ %s" % _brace(y_to if y_to is not None else "OFF"))
        axinfo["y"] = {"type": y_type or "dB",
                       "from": y_from if y_from is not None else "OFF (Auto)",
                       "to": y_to if y_to is not None else "OFF (Auto)"}
        steps["axis"] = axinfo
        _ev("catch {release $ax}; unset ax")
        _ev("catch {release $sd}; unset sd")

    _ev("catch {release $it}; unset it")
    return steps


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def pak_open_graphdef() -> dict:
    """Open (show) the PAK Graphic Definition window and confirm the connection."""
    try:
        _open_gd(visible=True)
        return {"ok": True, "message": "Graphic Definition opened."}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def release_all() -> dict:
    """Force-release all PAK COM handles. Use if a call left PAK in a locked state."""
    _reset()
    _close_gd()
    _reset()
    return {"ok": True, "message": "All PAK COM objects released."}


@mcp.tool()
def set_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
            measurement: str = "") -> dict:
    """Set a row's Active / Diagr. / Curve / Name of Measurement (1-based row)."""
    try:
        _open_gd()
        steps = _apply_row(row, active=active, diagram=diagram, curve=curve,
                           measurement=measurement or None)
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def set_data_type(row: int, position: str, direction: str, quantity: str,
                  measurement_data_type: str = "", graphic_data_type: str = "",
                  sampling_rate: str = "") -> dict:
    """Configure the Data type tab: channel position/direction/quantity + data types.

    Args:
        row: 1-based grid row.
        position: Measurement point, e.g. "Gear Lever".
        direction: S, +X, +Y, +Z, -X, -Y, -Z.
        quantity: e.g. "Acceleration".
        measurement_data_type: e.g. "Throughput".
        graphic_data_type: e.g. "APS".
        sampling_rate: e.g. "32768".
    """
    try:
        _open_gd()
        steps = _apply_row(row, position=position, direction=direction, quantity=quantity,
                           measurement_data_type=measurement_data_type or None,
                           graphic_data_type=graphic_data_type or None,
                           sampling_rate=sampling_rate or None)
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def set_track(row: int, track_quantity: str = "Time", start: str = "Min",
              stop: str = "Max", track_position: str = "",
              track_direction: str = "") -> dict:
    """Configure the Track parameter tab: Par.-channel + range (default Min..Max).

    Plain TIME track: leave track_position empty, track_quantity="Time".
    CHANNEL track that PAK requires a position label for (e.g. Distance in
    exterior/pass-by noise): pass track_position="Distance", track_direction="S",
    track_quantity="Cart. coord.x" (use the exact strings get_channels reports),
    start="-10", stop="20". Without the position, PAK raises
    "Working mode ... requires a position label".
    """
    try:
        _open_gd()
        steps = _apply_row(row, track_quantity=track_quantity,
                           track_position=track_position or None,
                           track_direction=track_direction or None,
                           track_start=start, track_stop=stop)
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def set_weighting(row: int, weighting: str) -> dict:
    """Set the frequency weighting (A / B / C / lin) for a row's data type.

    Tries the properties in PAK_WEIGHT_PROPS (default Tp2det_fweight,Tp2oct_fweight).
    """
    if weighting not in ("A", "B", "C", "lin"):
        return {"ok": False, "error": "weighting must be A, B, C or lin"}
    try:
        _open_gd()
        steps = _apply_row(row, weighting=weighting)
        ok = "weighting" in steps
        return {"ok": ok, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def graphic_output() -> dict:
    """Run Graphic Output (GraphDef.Graphicoutput) to render the definition."""
    try:
        _open_gd()
        _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)  # non-RMS -> standard layout
        _ev("$gd Graphicoutput")
        return {"ok": True, "message": "Graphic output executed."}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
                  measurement: str = "", position: str = "", direction: str = "",
                  quantity: str = "", measurement_data_type: str = "",
                  graphic_data_type: str = "", sampling_rate: str = "",
                  blocksize: str = "",
                  track_quantity: str = "Time", track_start: str = "Min",
                  track_stop: str = "Max",
                  track_position: str = "", track_direction: str = "",
                  weighting: str = "",
                  stat_parameter: str = "",
                  x_from: str = "", x_to: str = "", x_type: str = "",
                  y_type: str = "", y_from: str = "", y_to: str = "",
                  output: bool = False) -> dict:
    """Configure a full row (all tabs) in one call, then optionally run Graphic Output.

    Applies, in order: Active, Diagr., Curve, Name of Measurement, Data type
    (channel/direction/quantity + data types), Track parameter (from Min), and
    frequency weighting. Set output=True to render afterward.
    """
    try:
        _open_gd()
        steps = _apply_row(
            row,
            active=active, diagram=diagram, curve=curve,
            measurement=measurement or None,
            position=position or None, direction=direction or None,
            quantity=quantity or None,
            measurement_data_type=measurement_data_type or None,
            graphic_data_type=graphic_data_type or None,
            sampling_rate=sampling_rate or None,
            blocksize=blocksize or None,
            track_quantity=track_quantity, track_start=track_start, track_stop=track_stop,
            track_position=track_position or None, track_direction=track_direction or None,
            weighting=weighting or None,
            stat_parameter=stat_parameter or None,
            x_from=x_from or None, x_to=x_to or None, x_type=x_type or None,
            y_type=y_type or None, y_from=y_from or None, y_to=y_to or None,
        )
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)  # non-RMS -> standard layout
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def set_track_property(row: int, name: str, value: str) -> dict:
    """Set ANY property on a row's TrackingParams object by raw COM name.

    Use for fields not covered by dedicated tools (e.g. the Track parameter
    "Stat. parameter" -> try name="Statparam" value="Avg_q", etc.). Returns the
    error text if PAK rejects the name/value, so you can discover the right name.

    Args:
        row: 1-based grid row.
        name: exact COM property name on TrackingParams.
        value: value to set (e.g. "Avg_q", "Avg_lin").
    """
    try:
        _open_gd()
        idx = row - 1
        _ev("set it [$gd Item %d]" % idx)
        _ev("set tp [$it TrackingParams]")
        try:
            _ev("$tp %s %s" % (name, _brace(value)))
            ok, err = True, None
        except Exception as exc:
            ok, err = False, str(exc).splitlines()[0]
        _ev("catch {release $tp}; unset tp")
        _ev("catch {release $it}; unset it")
        return {"ok": ok, "row": row, "name": name, "value": value, "error": err}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def set_datatype_property(row: int, name: str, value: str) -> dict:
    """Set ANY property on a row's Datentyp (Data type) object by raw COM name.

    Escape hatch for fields not covered by dedicated tools.

    Args:
        row: 1-based grid row.
        name: exact COM property name on Datentyp.
        value: value to set.
    """
    try:
        _open_gd()
        idx = row - 1
        _ev("set it [$gd Item %d]" % idx)
        _ev("set dt [$it Datentyp]")
        try:
            _ev("$dt %s %s" % (name, _brace(value)))
            ok, err = True, None
        except Exception as exc:
            ok, err = False, str(exc).splitlines()[0]
        _ev("catch {release $dt}; unset dt")
        _ev("catch {release $it}; unset it")
        return {"ok": ok, "row": row, "name": name, "value": value, "error": err}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY rows and optionally run Graphic Output in ONE call / one COM
    session (much faster than calling configure_row repeatedly).

    Args:
        rows: JSON list of row objects. Each object needs "row" (1-based) plus any of:
              active, diagram, curve, measurement, position, direction, quantity,
              measurement_data_type, graphic_data_type, sampling_rate,
              track_quantity, track_position, track_direction, track_start,
              track_stop, weighting.
              For a Distance (exterior/pass-by) track pass track_position="Distance",
              track_direction="S", track_quantity="Cart. coord.x", track_start="-10",
              track_stop="20". Omit track_position for a plain Time track.
        deactivate_beyond: if > 0, any row in 1..deactivate_beyond NOT present in the
              list is set Active=0 (cleans up leftover rows). e.g. 6 clears rows 4-6
              when you only pass rows 1-3.
        output: run Graphic Output at the end (default True).

    Example rows:
      [{"row":1,"diagram":1,"curve":1,"measurement":"ExampleMOI/Acceleration_Run_01 [CP]",
        "position":"Gear Lever","direction":"+X","quantity":"Acceleration",
        "measurement_data_type":"Throughput","graphic_data_type":"APS","sampling_rate":"32768"}]
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "measurement_data_type", "graphic_data_type", "sampling_rate",
            "blocksize",
            "track_quantity", "track_position", "track_direction",
            "track_start", "track_stop", "weighting", "stat_parameter",
            "x_from", "x_to", "x_type", "y_type", "y_from", "y_to")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r)
            rownum = int(rr.get("row"))
            listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)  # rows are Active by default (match
            #   configure_row / output_rms); else bulk config leaves rows 2+ off.
            steps = _apply_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)  # non-RMS -> standard layout
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results, "deactivated_beyond": deactivate_beyond, "output": bool(output)}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def close_graphdef() -> dict:
    """Close (hide) the PAK Graphic Definition editor window (GraphDef.Visible=0)."""
    try:
        _open_gd(visible=False)
        _ev("$gd Visible 0")
        return {"ok": True, "message": "Graphic Definition window closed."}
    finally:
        _close_gd()
        _reset()


def _import_uiautomation():
    """Import uiautomation, adding the current user's site-packages to sys.path
    first (covers the case where the server runs with user-site disabled).
    Returns (module, None) on success or (None, error_str) on failure.
    """
    try:
        import uiautomation as auto
        return auto, None
    except Exception as first:
        try:
            import site
            for p in (site.getusersitepackages() if hasattr(site, "getusersitepackages") else []):
                pass
            usp = site.getusersitepackages() if hasattr(site, "getusersitepackages") else None
            if isinstance(usp, str) and usp not in sys.path and os.path.isdir(usp):
                sys.path.append(usp)
            import uiautomation as auto  # retry
            return auto, None
        except Exception as second:
            return None, "%s / retry: %s" % (first, second)


@mcp.tool()
def server_info() -> dict:
    """Diagnostics: which Python runs this MCP server, and can it import uiautomation.

    Returns the interpreter path/version, user site-packages dir, and the
    uiautomation import status (with its file path if importable).
    """
    import site
    auto, err = _import_uiautomation()
    info = {
        "ok": True,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "user_site_packages": site.getusersitepackages() if hasattr(site, "getusersitepackages") else None,
        "uiautomation_importable": auto is not None,
    }
    if auto is not None:
        info["uiautomation_path"] = getattr(auto, "__file__", None)
    else:
        info["uiautomation_error"] = err
    return info


@mcp.tool()
def reset_graphdef() -> dict:
    """Reset the Graphic Definition by sending Ctrl+N (New) to its window.

    Uses UI Automation only to focus the window and send the keystroke (no pixel
    clicks). Requires the 'uiautomation' package on the machine running the server.
    """
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err,
                "python": sys.executable, "version": sys.version.split()[0]}
    win = None
    for w in auto.GetRootControl().GetChildren():
        try:
            if "graphic definition" in (w.Name or "").lower():
                win = w
                break
        except Exception:
            pass
    if not win:
        return {"ok": False, "error": "Graphic Definition window not found (open it first)."}
    import time
    win.SetActive()
    win.SendKeys("{Ctrl}n")
    # A confirmation dialog ("New page?") pops up; Enter = default Yes.
    time.sleep(1.5)
    auto.SendKeys("{Enter}")
    return {"ok": True, "message": "Sent Ctrl+N then Enter (confirmed New)."}


# --------------------------------------------------------------------------- #
# Order (차수) analysis -- SEPARATE from APS. Datentyp "Order complex" +
# Item.Order (Ordfrom/Ordto/Ordlines/Bandwidth/Bwtype/SetChanposOrder) +
# TrackingParams (RPM track channel, Delta, Smooth). Confirmed property names.
# Fixed: Measurement=Throughput, Sampling=32768, Graphic=Order complex.
# Defaults: Blocksize 1024, Order 4, Max order 100, Order lines 400, Delta 20,
# Smoothing on (all overridable).
# --------------------------------------------------------------------------- #
def _apply_order_row(
    row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction=None, quantity=None,
    order=None, blocksize=None, par=None,
    max_order=None, order_from=None, order_lines=None,
    bandwidth=None, bwtype=None, searchbw=None,
    rpm_position=None, rpm_direction=None, rpm_quantity=None,
    delta=None, smoothing=None, track_start=None, track_stop=None,
    analysis_rpm_position=None, analysis_rpm_direction=None, analysis_rpm_quantity=None,
):
    """Configure one row as an Order analysis on an already-open GraphDef ($gd)."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)

    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement

    # --- Data type: Order complex ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(direction), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": direction, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Throughput"))
    _ev("$dt Srate %s" % _brace("32768"))
    _ev("$dt Pdtype %s" % _brace("Order complex"))
    _par = par if par is not None else "Magnitude"
    _ev("$dt Pdtypar %s" % _brace(_par)); steps["par"] = _par
    _bs = blocksize if blocksize is not None else "1024"
    _ev("$dt Tp2spec_blocksize %s" % _brace(_bs)); steps["blocksize"] = _bs
    _ordnum = order if order is not None else "4"
    _ev("$dt Order %s" % _brace(_ordnum)); steps["order"] = _ordnum
    # Maximum order: the WRITABLE property is Datentyp.Tp2spec_maxorder. The older
    # Item.Order.Ordto is READ-ONLY in this graphic definition (setting it raises
    # "Value can only be read"), so max order MUST be set here on the Datentyp.
    _momax = max_order if max_order is not None else "100"
    try:
        _ev("$dt Tp2spec_maxorder %s" % _brace(_momax)); steps["max_order"] = _momax
    except Exception:
        pass
    steps["measurement_data_type"] = "Throughput"
    steps["graphic_data_type"] = "Order complex"
    steps["sampling_rate"] = "32768"
    _ev("catch {release $dt}; unset dt")

    # --- Item.Order: order axis / bandwidth / (optional) analysis RPM channel ---
    # NOTE: several Item.Order properties (esp. Ordto) are read-only in the Order-APS
    # style definition, so every set here is BEST-EFFORT and must not abort the call.
    _ev("set ord [$it Order]")

    def _ordset(prop, val, key=None):
        try:
            _ev("$ord %s %s" % (prop, _brace(val)))
            if key:
                steps[key] = val
        except Exception:
            if key:
                steps[key + "_readonly"] = val

    _mo = max_order if max_order is not None else "100"
    _ordset("Ordto", _mo)  # read-only here; real max order set via Tp2spec_maxorder
    if order_from is not None:
        _ordset("Ordfrom", order_from, "order_from")
    _ol = order_lines if order_lines is not None else "400"
    _ordset("Ordlines", _ol, "order_lines")
    if bandwidth is not None:
        _ordset("Bandwidth", bandwidth, "bandwidth")
    if bwtype is not None:
        _ordset("Bwtype", bwtype, "bwtype")
    if searchbw is not None:
        _ordset("Searchbw", searchbw, "searchbw")
    if analysis_rpm_quantity:
        _ev("$ord SetChanposOrder %s %s %s" % (_brace(analysis_rpm_position),
            _brace(analysis_rpm_direction), _brace(analysis_rpm_quantity)))
        steps["analysis_rpm"] = {"position": analysis_rpm_position,
                                 "direction": analysis_rpm_direction,
                                 "quantity": analysis_rpm_quantity}
    _ev("catch {release $ord}; unset ord")

    # --- Track parameter: RPM channel as x-axis, Delta, Smoothing ---
    _ev("set tp [$it TrackingParams]")
    _rq = rpm_quantity or "Rotational Speed"
    _ev("$tp SetChanposTrack %s %s %s" % (_brace(rpm_position), _brace(rpm_direction), _brace(_rq)))
    steps["track_rpm_channel"] = {"position": rpm_position, "direction": rpm_direction, "quantity": _rq}
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    _dl = delta if delta is not None else "20"
    _ev("$tp Delta %s" % _brace(_dl)); steps["delta"] = _dl
    _sm = 0 if smoothing is False else 1
    _ev("$tp Smooth %d" % _sm); steps["smoothing"] = bool(_sm)
    _ev("catch {release $tp}; unset tp")

    _ev("catch {release $it}; unset it")
    return steps


@mcp.tool()
def configure_order_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
                        measurement: str = "", position: str = "", direction: str = "",
                        quantity: str = "", order: str = "4", blocksize: str = "1024",
                        par: str = "Magnitude",
                        max_order: str = "100", order_from: str = "", order_lines: str = "400",
                        bandwidth: str = "", bwtype: str = "",
                        rpm_position: str = "", rpm_direction: str = "S",
                        rpm_quantity: str = "Rotational Speed",
                        delta: str = "20", smoothing: bool = True,
                        track_start: str = "Min", track_stop: str = "Max",
                        output: bool = False) -> dict:
    """Configure one ORDER (차수) analysis row, then optionally run Graphic Output.

    Order analysis differs from APS: Graphic data type 'Order complex', a specific
    Order number, an order axis (max order / order lines), and an RPM track channel
    with Delta + Smoothing. Fixed: Measurement Throughput, Sampling 32768, Graphic
    'Order complex'. Defaults: Blocksize 1024, Order 4, Max order 100, Order lines
    400, Delta 20, Smoothing on.

    Args:
        position/direction/quantity: MEASURED channel (e.g. MOT_B1 +Z Acceleration).
        order: order number (Datentyp.Order).
        max_order/order_from/order_lines: order axis (Item.Order Ordto/Ordfrom/Ordlines).
        blocksize: FFT blocksize (Tp2spec_blocksize).
        rpm_position/rpm_direction/rpm_quantity: RPM track channel (Par.-Channel),
            e.g. CH65 / S / Rotational Speed.
        delta: RPM step (Delta). smoothing: track smoothing (on by default).
    """
    try:
        _open_gd()
        steps = _apply_order_row(
            row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or None, quantity=quantity or None,
            order=order or None, blocksize=blocksize or None, par=par or None,
            max_order=max_order or None, order_from=order_from or None,
            order_lines=order_lines or None, bandwidth=bandwidth or None,
            bwtype=bwtype or None,
            rpm_position=rpm_position or None, rpm_direction=rpm_direction or None,
            rpm_quantity=rpm_quantity or None, delta=delta or None, smoothing=smoothing,
            track_start=track_start, track_stop=track_stop,
        )
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)  # non-RMS -> standard layout
            _ev("$gd Graphicoutput")
        return {"ok": True, "row": row, "applied": steps, "output": bool(output)}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_order_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY ORDER-analysis rows in ONE COM session, then run Graphic Output.

    Args:
        rows: JSON list of row objects. Each needs "row" plus any of: active, diagram,
              curve, measurement, position, direction, quantity, order, blocksize,
              max_order, order_from, order_lines, bandwidth, bwtype, searchbw,
              rpm_position, rpm_direction, rpm_quantity, delta, smoothing,
              track_start, track_stop, analysis_rpm_position/direction/quantity.
        deactivate_beyond: deactivate rows 1..N not present in the list.
        output: run Graphic Output at the end.

    Example row:
      {"row":1,"diagram":1,"curve":1,"measurement":"ENG_01/Test_01 [CP]",
       "position":"MOT_B1","direction":"+Z","quantity":"Acceleration","order":"4",
       "rpm_position":"CH65","rpm_direction":"S","rpm_quantity":"Rotational Speed"}
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "order", "blocksize", "par", "max_order", "order_from", "order_lines",
            "bandwidth", "bwtype", "searchbw", "rpm_position", "rpm_direction",
            "rpm_quantity", "delta", "smoothing", "track_start", "track_stop",
            "analysis_rpm_position", "analysis_rpm_direction", "analysis_rpm_quantity")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r)
            rownum = int(rr.get("row"))
            listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)  # rows Active by default (bulk)
            steps = _apply_order_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)  # non-RMS -> standard layout
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# Working mode  (GraphDef.Optionen.Modus)
# --------------------------------------------------------------------------- #
_MODE_MAP = {"channel": "Kanalorientiert", "position": "Positionsorientiert"}
_MODE_REV = {v: k for k, v in _MODE_MAP.items()}


@mcp.tool()
def get_working_mode() -> dict:
    """Read the Graphic Definition working mode (GraphDef.Optionen.Modus).

    Returns modus ('Kanalorientiert'/'Positionsorientiert') and a friendly
    'mode' ('channel'/'position').
    """
    try:
        _open_gd()
        _ev("set opt [$gd Optionen]")
        modus = _ev("$opt Modus")
        _ev("catch {release $opt}; unset opt")
        return {"ok": True, "modus": modus, "mode": _MODE_REV.get(modus, modus)}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def set_working_mode(mode: str) -> dict:
    """Set the Graphic Definition working mode.

    Args:
        mode: 'channel'/'position' (or raw 'Kanalorientiert'/'Positionsorientiert').

    Channel-oriented uses SetChan (channel number); position-oriented uses
    SetChanpos (position/direction). Our tools use position-oriented.
    """
    m = _MODE_MAP.get(mode.lower(), mode)
    try:
        _open_gd()
        _ev("set opt [$gd Optionen]")
        _ev("$opt Modus %s" % _brace(m))
        now = _ev("$opt Modus")
        _ev("catch {release $opt}; unset opt")
        return {"ok": True, "requested": m, "modus": now,
                "mode": _MODE_REV.get(now, now)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# Pages (sheets).  COM can navigate existing pages (GraphDef.Page) but CANNOT
# create them -- new page is a UI action (name dialog), done via UI Automation.
# --------------------------------------------------------------------------- #
@mcp.tool()
def list_pages() -> dict:
    """List Graphic Definition pages (sheets): count + current page name."""
    try:
        _open_gd()
        try:
            count = _ev("$gd PageCount")
        except Exception:
            count = "?"
        try:
            current = _ev("$gd Page")
        except Exception:
            current = "?"
        return {"ok": True, "page_count": count, "current_page": current}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def goto_page(page: str) -> dict:
    """Switch the active Graphic Definition page (sheet).

    Args:
        page: page name, or 'First' / 'Next'. Only EXISTING pages (COM cannot
              create pages -- use new_page for that).
    """
    try:
        _open_gd()
        try:
            _ev("$gd Page %s" % _brace(page))
            current = _ev("$gd Page")
            return {"ok": True, "current_page": current}
        except Exception as exc:
            return {"ok": False, "error": str(exc).splitlines()[0],
                    "hint": "page must already exist; use new_page to create it"}
    finally:
        _close_gd()
        _reset()


def _find_page_buttons(auto):
    """Return (win, [new_btn, delete_btn]) — the New/Delete page buttons.

    DPI/resolution-agnostic: anchors on the page-tab (TabControl/TabItem) and
    picks the ButtonControls that sit in the same row, to its right, and extend
    below the tab (that's what distinguishes the page buttons from scrollbar
    arrows). No absolute pixel sizes. Falls back to a size heuristic if no tab
    is found.
    """
    win = None
    for w in auto.GetRootControl().GetChildren():
        try:
            if "graphic definition" in (w.Name or "").lower():
                win = w
                break
        except Exception:
            pass
    if not win:
        return None, []

    tab = None          # the page-tab control
    buttons = []        # (left, top, bottom, control)

    def walk(ctrl, depth=0):
        nonlocal tab
        for c in ctrl.GetChildren():
            try:
                ct = c.ControlTypeName
                br = c.BoundingRectangle
                if ct in ("TabControl", "TabItemControl") and tab is None:
                    tab = br
                elif ct == "ButtonControl" and br.width() > 0:
                    buttons.append((br.left, br.top, br.bottom, c))
            except Exception:
                pass
            if depth < 8:
                walk(c, depth + 1)

    walk(win)

    if tab is not None:
        row_top, row_bottom, tab_right = tab.top, tab.bottom, tab.right
        cand = []
        for left, top, bottom, c in buttons:
            # same row as the tab, to its right, and extending below the tab
            if left >= tab_right - 6 and top <= row_bottom + 6 and bottom >= row_bottom + 4:
                cand.append((left, c))
        cand.sort(key=lambda t: t[0])       # left-to-right: new, delete
        if len(cand) >= 1:
            return win, [c for _, c in cand]

    # Fallback: small buttons in the bottom strip (old heuristic)
    wb = win.BoundingRectangle.bottom
    fb = []
    for left, top, bottom, c in buttons:
        w = c.BoundingRectangle.width()
        h = c.BoundingRectangle.height()
        if 20 <= w <= 60 and 30 <= h <= 70 and top >= wb - 200:
            fb.append((left, c))
    fb.sort(key=lambda t: t[0])
    return win, [c for _, c in fb]


@mcp.tool()
def new_page(name: str) -> dict:
    """Create a NEW Graphic Definition page (sheet) named <name>, via UI Automation.

    COM cannot create pages, so this clicks the 'New page' (paper) button at the
    bottom-left of the page-tab bar, types the name into the 'Please enter a name
    for the new page' dialog, and confirms. Requires 'uiautomation'.
    """
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err}
    import time
    win, btns = _find_page_buttons(auto)
    if not win:
        return {"ok": False, "error": "Graphic Definition window not found (open it first)."}
    if len(btns) < 1:
        return {"ok": False, "error": "New-page button not found near the page-tab bar."}
    win.SetActive()
    time.sleep(0.3)
    btns[0].Click(simulateMove=False)       # leftmost = New page (paper)
    time.sleep(0.8)                          # wait for name dialog
    auto.SendKeys("{Ctrl}a", waitTime=0.05)  # clear any default
    auto.SendKeys(name, waitTime=0.05)
    time.sleep(0.3)
    auto.SendKeys("{Enter}")
    time.sleep(0.4)
    return {"ok": True, "name": name, "buttons_found": len(btns)}


@mcp.tool()
def delete_page() -> dict:
    """Delete the CURRENT Graphic Definition page, via UI Automation.

    Clicks the 'Delete page' (paper-with-X) button right of the page-tab bar and
    confirms Yes. Requires 'uiautomation'.
    """
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err}
    import time
    win, btns = _find_page_buttons(auto)
    if not win:
        return {"ok": False, "error": "Graphic Definition window not found (open it first)."}
    if len(btns) < 2:
        return {"ok": False, "error": "Delete-page button not found near the page-tab bar."}
    win.SetActive()
    time.sleep(0.3)
    btns[1].Click(simulateMove=False)        # second = Delete page (paper-X)
    time.sleep(0.8)                           # wait for confirm dialog
    auto.SendKeys("{Enter}")                  # Yes
    time.sleep(0.4)
    return {"ok": True, "buttons_found": len(btns)}


# --------------------------------------------------------------------------- #
# Save / Open the Graphic Definition file  (Editor interface: Save/SaveAs/Open/Name)
# --------------------------------------------------------------------------- #
@mcp.tool()
def save_graphdef(filename: str = "") -> dict:
    """Save the current Graphic Definition to a file (all pages included).

    Args:
        filename: file to save to. A bare name is stored in PAK's user Tables
            (PlotEditor) directory; a full path (e.g. C:/.../MyDef) saves there.
            If empty, saves to the last-used file name (Save).

    Use this to persist your work (pages/rows) so it isn't lost when PAK resets.
    """
    try:
        _open_gd()
        if filename:
            _ev("$gd SaveAs %s" % _brace(filename))
        else:
            _ev("$gd Save")
        try:
            name = _ev("$gd Name")
        except Exception:
            name = ""
        return {"ok": True, "saved_as": filename or name, "name": name}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def open_graphdef_file(filename: str) -> dict:
    """Load a Graphic Definition from a file (Editor.Open).

    Args:
        filename: a bare name (from PAK user Tables/PlotEditor) or a full path.
    """
    try:
        _open_gd()
        _ev("$gd Open %s" % _brace(filename))
        try:
            name = _ev("$gd Name")
        except Exception:
            name = ""
        return {"ok": True, "opened": filename, "name": name}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def list_graphdefs() -> dict:
    """List saved Graphic Definition files (PlotEditor) in PAK's table dirs.

    Reads Tablepath / GroupStandards / CompanyStandards, then enumerates each
    'PlotEditor' subfolder. Returns the folders and their file names.
    """
    try:
        _ensure_sourced()
        _ev("set reference [createobject $pak_application]")
        bases = {}
        for p in ("Tablepath", "GroupStandards", "CompanyStandards", "Adminpath"):
            try:
                v = _ev("$reference %s" % p)
            except Exception:
                v = ""
            if v:
                bases[p] = v
        _ev("catch {release $reference}; unset reference")
    except Exception as exc:
        return {"ok": False, "error": str(exc).splitlines()[0]}
    finally:
        _reset()

    folders = []
    seen = set()
    for label, base in bases.items():
        cand = os.path.normpath(os.path.join(base.replace("\\", "/"), "PlotEditor"))
        if cand in seen or not os.path.isdir(cand):
            continue
        seen.add(cand)
        files = [f for f in sorted(os.listdir(cand))
                 if os.path.isfile(os.path.join(cand, f))]
        folders.append({"path": cand, "source": label,
                        "count": len(files), "files": files})
    return {"ok": True, "table_paths": bases, "folders": folders}


@mcp.tool()
def graphdef_name() -> dict:
    """Return the current Graphic Definition file name (Editor.Name)."""
    try:
        _open_gd()
        try:
            name = _ev("$gd Name")
        except Exception:
            name = ""
        return {"ok": True, "name": name}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# RMS (band-pass Sum level) -- sets the RMS layout, configures channels as APS
# with band 0..1000 Hz + Sum level 1 = 'Bandpass mag', runs Graphic Output.
# The RMS values render as a table on the graph; capture it as an image to read.
# --------------------------------------------------------------------------- #
def _capture_viewer(png_path):
    """Screenshot the Graphic Viewer window to png_path. Needs pillow + uiautomation
    on a Windows session WITH a visible desktop (i.e. the local desktop MCP host --
    Claude Desktop / Cowork). Never raises: on any failure it returns a friendly,
    actionable message so the caller's analysis/render still succeeds and only the
    screenshot is skipped. Returns (ok, info): info is a dict on success, a guidance
    string on failure. Capture is NOT available in web/mobile chat (no local tools)."""
    try:
        import time
        import uiautomation as auto
        from PIL import ImageGrab
    except Exception as e:
        return False, ("Screen capture skipped: needs 'pillow' + 'uiautomation' on a "
                       "Windows session with a display. Install with: "
                       "pip install pillow uiautomation. Analysis/render still completed "
                       "-- only the screenshot was skipped. (%s)" % e)
    try:
        win = None
        for w in auto.GetRootControl().GetChildren():
            try:
                if w.ControlTypeName == "WindowControl" and "graphic viewer" in (w.Name or "").lower():
                    win = w
                    break
            except Exception:
                pass
        if not win:
            return False, ("Screen capture skipped: PAK 'Graphic Viewer' window not found. "
                           "Run Graphic Output so the viewer is open on a visible Windows "
                           "desktop, then capture. (Not available in web/mobile chat -- "
                           "capture needs the local desktop MCP host.)")
        try:
            win.SetActive()
        except Exception:
            pass
        time.sleep(0.6)
        r = win.BoundingRectangle
        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
        img.save(png_path)
        return True, {"path": png_path, "size": list(img.size)}
    except Exception as e:
        return False, ("Screen capture skipped: could not grab the viewer window "
                       "(headless session or no display?). Analysis/render still "
                       "completed. (%s)" % e)


@mcp.tool()
def capture_viewer(path: str = "C:/MCPproject_pak/view_shot.png") -> dict:
    """Screenshot the PAK Graphic Viewer window to `path` -- the SAME capture that
    output_rms uses (reads the currently displayed graph, any analysis: Order APS,
    Order complex, APS, etc.). Default path C:/MCPproject_pak/view_shot.png. Use this
    to grab the current screen so the result can be read from the image without
    reconfiguring anything."""
    ok, info = _capture_viewer(path)
    if ok:
        return {"ok": True, "capture": info}
    return {"ok": False, "error": info}


def _capture_inline(path):
    """Capture the viewer, then read the PNG bytes SERVER-SIDE and wrap them as an MCP
    Image so the screenshot renders INLINE in the chat -- no client file-path access
    needed (fixes 'path not accessible' in the plain chat client). Returns
    (image_or_None, info): image is an mcp Image on success, else None with a message.
    The server can always read the file it just wrote even when the client cannot."""
    ok, info = _capture_viewer(path)
    if not ok:
        return None, info
    try:
        from mcp.server.fastmcp import Image
        with open(path, "rb") as _fh:
            data = _fh.read()
        return Image(data=data, format="png"), info
    except Exception as e:
        return None, ("capture saved to %s but inline image unavailable on this MCP SDK "
                      "(%s); read the file instead." % (path, e))


@mcp.tool()
def capture_viewer_inline(path: str = "C:/MCPProject_pak/view_shot.png"):
    """Screenshot the PAK Graphic Viewer and return it as an INLINE image in the
    response (base64), so it shows directly in chat WITHOUT the client needing to open
    the saved file. Use this when the client cannot access the capture folder (e.g. the
    plain chat client reports the path is not accessible) -- the server reads the PNG it
    just wrote and embeds it. Falls back to a message if inline image isn't supported."""
    img, info = _capture_inline(path)
    if img is not None:
        return img
    return {"ok": False, "capture": info}


def _find_viewer_window(auto):
    """Return the PAK 'Graphic Viewer' top-level window, or None."""
    for w in auto.GetRootControl().GetChildren():
        try:
            if w.ControlTypeName == "WindowControl" and "graphic viewer" in (w.Name or "").lower():
                return w
        except Exception:
            pass
    return None


def _parse_num(s):
    """Extract the first numeric value from a readout string (handles a trailing
    unit like ' s' or ' dB', and comma decimals)."""
    if s is None:
        return None
    import re
    m = re.search(r"[-+]?\d*[.,]?\d+(?:[eE][-+]?\d+)?", str(s))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except Exception:
        return None


def _read_cursor_readout(auto):
    """Read the Graphic Viewer cursor readout: X1/Y1 (master cursor) and, if set,
    X2/Y2 (second cursor), plus a Project/measurement banner. Returns a dict
    {raw:{X1,Y1,X2,Y2,DX,DY}, banner} or None if the window is not found.

    Mirrors pak_read_y1.py: find the label TextControls ('X1:', 'X2:', ...) and pair
    each with the nearest EditControl to its right on the same row (the value)."""
    import re
    win = _find_viewer_window(auto)
    if not win:
        return None
    labels = {}
    edits = []
    banner = ""
    LAB = re.compile(r"^(X1|X2|Y1|Y2|dX|dY)\s*:?$", re.I)

    def walk(c, d=0):
        nonlocal banner
        for ch in c.GetChildren():
            try:
                ct = ch.ControlTypeName
                nm = (ch.Name or "").strip()
                r = ch.BoundingRectangle
                if ct == "TextControl" and LAB.match(nm):
                    labels[nm.rstrip(":").upper()] = r
                elif ct == "TextControl" and nm.lower().startswith("project:"):
                    banner = nm
                elif ct == "EditControl":
                    try:
                        v = ch.GetValuePattern().Value or ""
                    except Exception:
                        v = ""
                    edits.append((r.left, r.top, v))
            except Exception:
                pass
            if d < 10:
                walk(ch, d + 1)

    walk(win)

    def near(lbl):
        r = labels.get(lbl)
        if not r:
            return None
        best = None
        bd = 1e9
        for (x, y, v) in edits:
            if abs(y - r.top) < 20 and x >= r.left - 2 and (x - r.left) < bd:
                bd = x - r.left
                best = v
        return best

    raw = {}
    for k in ("X1", "Y1", "X2", "Y2", "DX", "DY"):
        v = near(k)
        if v not in (None, ""):
            raw[k] = v
    return {"raw": raw, "banner": banner}


@mcp.tool()
def read_viewer_cursors() -> dict:
    """Read the PAK Graphic Viewer cursor readout (X1/Y1 and, if a 2nd cursor is set,
    X2/Y2) via UI Automation -- READ ONLY, no clicks.

    For a TIME-domain curve the X values are the measurement time (t=0 at the
    trigger/starttime), so this returns the time(s) at the cursor(s). Use it after
    selecting a segment on the GPS-synced map (map-pin icon in the Graphic Viewer)
    or placing two cursors: it gives t1/t2, which you then feed to
    output_rms(track_start=t1, track_stop=t2) to compute the band-pass RMS over just
    that segment.

    Returns: ok, cursors (raw X1/Y1/X2/Y2 strings), t1/t2 (numeric, the sorted X of
    the available cursors), banner (Project/measurement), and a note if only one
    cursor is present.
    """
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err}
    import time
    res = None
    for _ in range(12):
        res = _read_cursor_readout(auto)
        if res and res.get("raw", {}).get("X1") is not None:
            break
        time.sleep(0.25)
    if not res:
        return {"ok": False,
                "error": "Graphic Viewer window not found. Run a Graphic Output first."}
    raw = res["raw"]
    x1 = _parse_num(raw.get("X1"))
    x2 = _parse_num(raw.get("X2"))
    xs = [x for x in (x1, x2) if x is not None]
    out = {"ok": True, "cursors": raw, "banner": res.get("banner", "")}
    if len(xs) >= 2:
        out["t1"] = round(min(xs), 4)
        out["t2"] = round(max(xs), 4)
    elif len(xs) == 1:
        out["t1"] = round(xs[0], 4)
        out["note"] = ("Only one cursor (X1) found -- set a second cursor (or select a "
                       "range on the map) to get t2.")
    else:
        out["ok"] = False
        out["error"] = "No numeric X cursor value could be read from the viewer."
    return out


# DISABLED (2026-07-17): Ctrl+A autoscales only the active/first diagram in a
# multi-diagram layout, so it is unreliable there. Decorator removed so this is
# NOT registered as an MCP tool. To re-enable, restore the '@mcp.tool()' line.
# @mcp.tool()
def autoscale_viewer(capture: bool = False, path: str = "C:/MCPproject_pak/view_shot.png") -> dict:
    """Auto-scale all axes of the PAK Graphic Viewer by sending Ctrl+A to its window.

    Mirrors the interactive 'Ctrl+A' autoscale: fits every diagram's axes to the
    displayed data, so curves that ran past a fixed Y-max (clipped at the top
    frame) become fully visible. Y/X axis Begin/End switch to AUTO. Uses UI
    Automation only (focus window + keystroke), no pixel clicks. Requires the
    'uiautomation' package on the machine running the server.

    Args:
        capture: if True, screenshot the viewer afterwards to `path`.
        path: screenshot destination when capture=True (default view_shot.png).
    """
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err,
                "python": sys.executable, "version": sys.version.split()[0]}
    win = _find_viewer_window(auto)
    if not win:
        return {"ok": False, "error": "Graphic Viewer window not found (open/output a graph first)."}
    import time
    try:
        win.SetActive()
    except Exception:
        pass
    time.sleep(0.3)
    win.SendKeys("{Ctrl}a")
    time.sleep(0.6)
    result = {"ok": True, "message": "Sent Ctrl+A (autoscale all axes) to Graphic Viewer."}
    if capture:
        ok, info = _capture_viewer(path)
        if ok:
            result["capture"] = info
        else:
            result["capture_error"] = info
    return result


@mcp.tool()
def output_rms(rows: str, band_from: str = "0", band_to: str = "1000",
               layout: str = "RMS.vas_dly", stat_parameter: str = "Average [Q]",
               deactivate_beyond: int = 0, capture: bool = True,
               draw_table: bool = True, weighting: str = "",
               sound_weighting: str = "A",
               track_start: str = "Min", track_stop: str = "Max") -> dict:
    """Compute band-pass RMS (Sum level 1 = 'Bandpass mag') over [band_from,band_to]
    Hz for the given channels, using the RMS layout, and run Graphic Output. The
    RMS values are drawn as a table on the graph (Test / S.Hz / E.Hz / RMS).

    Args:
        rows: JSON list, each {row, diagram, curve, measurement, position,
              direction, quantity}. (Channels to include; group by diagram.)
              Each row may ALSO carry its own "track_start"/"track_stop" — these
              override the global window for that row, so ONE call can give each
              measurement a DIFFERENT time window (e.g. the same GPS location across
              speeds -> different t per run) and render everything in a SINGLE output.
        band_from / band_to: RMS frequency band in Hz.
        layout: graphic layout name that renders the RMS table (Optionen.Foname).
        deactivate_beyond: deactivate rows 1..N not in the list.
        capture: if True and pillow is installed, screenshot the Graphic Viewer to
              C:/MCPproject_pak/rms_shot.png so the values can be read from the image.
        draw_table: True (default) draws the RMS value table via the layout. False
              outputs the 2D comparison curves only, with NO RMS table (equivalent to
              setting the toolbar "Layout" to None); the band-pass Sum level is skipped.
        weighting: force a frequency weighting ("A"/"B"/"C"/"lin") on ALL rows.
        sound_weighting: weighting auto-applied to Sound Pressure channels when
              `weighting` is not set (default "A" -- sound is analysed A-weighted).
              Set "" or "lin" to disable auto-weighting for sound.
        track_start / track_stop: TIME window (seconds, t=0 at trigger) over which
              the band-pass RMS is averaged. Default "Min"/"Max" = whole record. To
              analyse only a GPS-selected segment, pass the cursor times t1/t2 (e.g.
              from read_viewer_cursors) -- the RMS is then averaged over [t1,t2] only.

    Fully automatic and reset-safe: sets Optionen.Format ("Autoformat" for the table,
    "Auto" = Layout None for curves-only), auto-creates the layout file, and sets the
    band-pass Sum level per row (token special char is U+00DE, built Tcl-side).
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    try:
        _open_gd()
        # Band-pass Sum level 1 token. In this PAK/Tcl bridge the special character
        # is U+00DE (reads back as 'BandpaÞ mag'), NOT the sz-ligature U+00DF. Build
        # it on the Tcl side via Þ so Python never touches the raw byte. It is
        # applied per-row AFTER each row is configured as APS -- the token only
        # appears in N1gesp's selection list once the row is an APS spectrum with a
        # band-pass range, so it cannot be set on an empty/reset row up front.
        _ev('set SUMTOK "Bandpa\\u00de mag"')
        sumtok = _ev("set SUMTOK") if draw_table else "(table off)"
        # ensure the RMS layout file exists (auto-create for users without it)
        try:
            _tp = _ev("$reference Tablepath")
            _tgt = os.path.join(_tp.replace("\\", "/"), "AutoFormat", "RMS.vas_dly")
            if os.path.exists(_RMS_LAYOUT_TEMPLATE) and not os.path.exists(_tgt):
                _write_rms_layout(_tgt, 0)
        except Exception:
            pass
        # Layout control. Optionen.Foname is read-only UNLESS Optionen.Format is
        # "Autoformat" (that mode auto-applies a layout from the AutoFormat folder).
        # So set Format="Autoformat" FIRST, then Foname becomes writable even from an
        # empty state -- no UI step needed.
        #   draw_table True  -> RMS value-table layout (RMS.vas_dly)
        #   draw_table False -> NO RMS table; force the standard layout (standard.vas_dly)
        if not draw_table:
            _ensure_layout_in_autoformat(_STD_LAYOUT_TEMPLATE, "standard.vas_dly")
        try:
            _ev("set opt [$gd Optionen]")
            try:
                _ev("$opt Format %s" % _brace("Autoformat"))
            except Exception:
                pass
            _ev("$opt Foname %s" % _brace(layout if draw_table else "standard.vas_dly"))
            _ev("catch {release $opt}; unset opt")
        except Exception:
            _ev("catch {release $opt}; unset opt")

        listed = set()
        applied = []
        for e in data:
            row = int(e["row"]); listed.add(row)
            _ev("set it [$gd Item %d]" % (row - 1))
            _ev("$it Active 1")
            _ev("$it Diag %d" % int(e.get("diagram", 1)))
            _ev("$it Curve %d" % int(e.get("curve", 1)))
            if e.get("measurement"):
                _ev("$it Datafile %s" % _brace(_cp_suffix(e["measurement"])))
            _ev("set dt [$it Datentyp]")
            _ev("$dt SetChanpos %s %s %s" % (_brace(e.get("position")),
                _brace(e.get("direction")), _brace(e.get("quantity"))))
            _ev("$dt Mdtype %s" % _brace("Throughput"))
            _ev("$dt Srate %s" % _brace("32768"))
            _ev("$dt Pdtype %s" % _brace("APS"))
            _ev("$dt Bplevelfrom %s" % _brace(band_from))
            _ev("$dt Bplevelto %s" % _brace(band_to))
            # Determine frequency weighting: explicit `weighting` wins; otherwise
            # auto-apply `sound_weighting` (default "A") to Sound Pressure channels
            # (sound is almost always A-weighted). Actually applied below via
            # Item.DarstFilter (the writable Freq. weighting field).
            _wt = weighting
            if not _wt:
                _q = (e.get("quantity") or "").lower()
                if sound_weighting and ("sound" in _q or "pressure" in _q):
                    _wt = sound_weighting
            if _wt and _wt.lower() != "lin":
                e["_weighting"] = _wt
            _ev("catch {release $dt}; unset dt")
            # 2D reduction so multiple curves overlay in one diagram (else APS is
            # 3D and PAK rejects two 3D curves per diagram).
            if stat_parameter and stat_parameter != "-":
                _tok = STAT_MAP.get(stat_parameter, stat_parameter)
                # Per-row time window overrides the global track_start/track_stop, so a
                # single output_rms call can give each measurement its OWN window (e.g.
                # same GPS location across speeds -> different t) and render ONCE.
                _rts = e.get("track_start", track_start)
                _rtp = e.get("track_stop", track_stop)
                _ev("set tp [$it TrackingParams]")
                _ev("$tp SetChanposTrack {} {} %s" % _brace("Time"))
                _ev("$tp Start %s" % _brace(_rts))
                _ev("$tp Stop %s" % _brace(_rtp))
                _ev("$tp Stats %s" % _brace(_tok))
                _ev("catch {release $tp}; unset tp")
            # Set Sum level 1 = band-pass magnitude now that the row is APS.
            # Only needed for the RMS value table; skipped for curves-only output.
            if draw_table:
                _ev("set gp [$it GesPegel]")
                try:
                    _ev("$gp N1gesp $SUMTOK")
                except Exception:
                    # locale/codepoint fallbacks (other installs may differ)
                    for _snip in (r'$gp N1gesp "Bandpa\u00df mag"',
                                  r'$gp N1gesp {Band pass mag}',
                                  r'$gp N1gesp {Bandpass mag}'):
                        try:
                            _ev(_snip)
                            break
                        except Exception:
                            continue
                try:
                    sumtok = _ev("$gp N1gesp")   # report the value actually applied
                except Exception:
                    pass
                _ev("catch {release $gp}; unset gp")
            # Apply the frequency weighting via Item.DarstFilter.Fweight -- this is
            # the WRITABLE "Freq. weighting" field (Datentyp.Tp2det_fweight is a no-op
            # for the band-pass RMS; GesPegel.N1fbew is read-only). DarstFilter is an
            # Item sub-object, so all other sub-objects (dt/tp/gp) must be released
            # first (they are, above).
            _rw = e.get("_weighting")
            if _rw:
                _ev("set df [$it DarstFilter]")
                try:
                    _ev("$df Fweight %s" % _brace(_rw))
                except Exception:
                    pass
                _ev("catch {release $df}; unset df")
            # The band-pass Sum level integrates over the displayed frequency (x)
            # axis, so set the X axis to [band_from, band_to]; Y = dB Auto.
            _ev("set sd [$it SkalenDefinition]")
            _ev("set ax [$sd AchsenSkalierung]")
            _ev("$ax Aktiv1_ 1"); _ev("$ax Type1_ %s" % _brace("lin"))
            _ev("$ax Von1_ %s" % _brace(band_from)); _ev("$ax Bis1_ %s" % _brace(band_to))
            _ev("$ax Aktiv2_ 1"); _ev("$ax Type2_ %s" % _brace("dB"))
            _ev("$ax Von2_ %s" % _brace("OFF")); _ev("$ax Bis2_ %s" % _brace("OFF"))
            _ev("catch {release $ax}; unset ax")
            _ev("catch {release $sd}; unset sd")
            _ev("catch {release $it}; unset it")
            applied.append({"row": row, "diagram": int(e.get("diagram", 1)),
                            "curve": int(e.get("curve", 1)),
                            "measurement": e.get("measurement"),
                            "weighting": e.get("_weighting", "lin"),
                            "channel": {"position": e.get("position"),
                                        "direction": e.get("direction"),
                                        "quantity": e.get("quantity")}})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        _ev("$gd Graphicoutput")
    finally:
        _close_gd()
        _reset()

    result = {"ok": True, "layout": layout, "band_hz": [band_from, band_to],
              "sumlevel_token": sumtok, "rows": applied}
    if sumtok.strip() in ("-", ""):
        result["warning"] = ("Row 1 Sum level 1 is not 'Bandpass mag' -- set it once "
                             "in PAK (Data definition > Sum level) then retry.")
    if capture:
        ok, info = _capture_viewer("C:/MCPproject_pak/rms_shot.png")
        result["capture"] = info if ok else {"error": info,
                             "hint": "pip install pillow, or share a screenshot"}
    return result


# --------------------------------------------------------------------------- #
# Order APS (차수 스펙트럼) -- order-frequency spectrum. Distinct from "Order
# complex" (single-order magnitude). Datentyp Pdtype "Order APS" + Tp2spec_blocksize
# + Tp2spec_maxorder (Copy Items token TP2SPEC_MAXORDER). Order lines / order resol.
# are derived from blocksize (not set). Needs an RPM track channel + Delta.
# Fixed: Throughput, Srate 32768, Max order 100. Blocksize 512 (variable).
# (Track Average mode/number deferred -- add later.)
# --------------------------------------------------------------------------- #
def _apply_orderaps_row(row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction=None, quantity=None,
    blocksize=None, max_order=None,
    rpm_position=None, rpm_direction=None, rpm_quantity=None,
    delta=None, track_start=None, track_stop=None,
    x_from=None, x_to=None, weighting=None, sound_weighting="A"):
    """Configure one row as an Order APS analysis on an already-open $gd."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: Order APS ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(direction), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": direction, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Throughput"))
    _ev("$dt Srate %s" % _brace("32768"))
    _ev("$dt Pdtype %s" % _brace("Order APS"))
    _bs = blocksize if blocksize is not None else "512"
    _ev("$dt Tp2spec_blocksize %s" % _brace(_bs)); steps["blocksize"] = _bs
    _mo = max_order if max_order is not None else "100"
    _ev("$dt Tp2spec_maxorder %s" % _brace(_mo)); steps["max_order"] = _mo
    steps["measurement_data_type"] = "Throughput"
    steps["graphic_data_type"] = "Order APS"
    steps["sampling_rate"] = "32768"
    _ev("catch {release $dt}; unset dt")
    # --- Frequency weighting (sound ALWAYS A-weighted) via Item.DarstFilter.Fweight ---
    _emit_sound_fweight(quantity, weighting, sound_weighting, steps)
    # --- Track parameter: RPM channel as x-axis + Delta ---
    _ev("set tp [$it TrackingParams]")
    _rq = rpm_quantity or "Rotational Speed"
    _ev("$tp SetChanposTrack %s %s %s" % (_brace(rpm_position), _brace(rpm_direction), _brace(_rq)))
    steps["track_rpm_channel"] = {"position": rpm_position, "direction": rpm_direction, "quantity": _rq}
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    _dl = delta if delta is not None else "25"
    _ev("$tp Delta %s" % _brace(_dl)); steps["delta"] = _dl
    _ev("catch {release $tp}; unset tp")
    # --- X-axis (order) display range: like an APS frequency range, but in orders.
    #     Keeps the full computation (Max order) and only zooms the displayed axis. ---
    if x_from is not None or x_to is not None:
        _ev("set sd [$it SkalenDefinition]")
        _ev("set ax [$sd AchsenSkalierung]")
        _ev("$ax Aktiv1_ 1"); _ev("$ax Type1_ %s" % _brace("lin"))
        if x_from is not None:
            _ev("$ax Von1_ %s" % _brace(x_from))
        if x_to is not None:
            _ev("$ax Bis1_ %s" % _brace(x_to))
        steps["x_axis"] = {"from": x_from, "to": x_to}
        _ev("catch {release $ax}; unset ax")
        _ev("catch {release $sd}; unset sd")
    _ev("catch {release $it}; unset it")
    return steps


@mcp.tool()
def configure_orderaps_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
    measurement: str = "", position: str = "", direction: str = "", quantity: str = "",
    blocksize: str = "512", max_order: str = "100",
    rpm_position: str = "", rpm_direction: str = "S", rpm_quantity: str = "Rotational Speed",
    delta: str = "25", track_start: str = "Min", track_stop: str = "Max",
    x_from: str = "", x_to: str = "",
    output: bool = False) -> dict:
    """Configure one ORDER APS (차수 스펙트럼) row, then optionally run Graphic Output.

    Order APS = order-frequency spectrum (Graphic data type 'Order APS'). Fixed:
    Measurement Throughput, Sampling 32768, Maximum order 100 (Tp2spec_maxorder).
    Blocksize 512 (variable, Tp2spec_blocksize; Order lines / Order resol. are derived
    from it). Needs an RPM track channel (Par.-Channel, Quantity 'Rotational Speed')
    + Delta (RPM step, default 25). Track Average mode/number are NOT set here.

    Args:
        position/direction/quantity: MEASURED channel (e.g. Gear Lever +X Acceleration).
        blocksize: FFT blocksize. max_order: maximum order (default 100).
        rpm_position/rpm_direction/rpm_quantity: RPM track channel. If several RPM
            channels exist, pass the first (report the others to the user).
        delta: RPM step.
    """
    try:
        _open_gd()
        steps = _apply_orderaps_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or None, quantity=quantity or None,
            blocksize=blocksize or None, max_order=max_order or None,
            rpm_position=rpm_position or None, rpm_direction=rpm_direction or None,
            rpm_quantity=rpm_quantity or None, delta=delta or None,
            track_start=track_start, track_stop=track_stop,
            x_from=x_from or None, x_to=x_to or None)
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_orderaps_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY ORDER APS rows in ONE COM session, then run Graphic Output.

    Each row object: row plus any of active/diagram/curve/measurement/position/
    direction/quantity/blocksize/max_order/rpm_position/rpm_direction/rpm_quantity/
    delta/track_start/track_stop. Fixed per row: Throughput, 32768, Pdtype 'Order APS',
    Max order 100 (unless overridden), Blocksize 512. Non-RMS -> standard.vas_dly layout.
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "blocksize", "max_order", "rpm_position", "rpm_direction",
            "rpm_quantity", "delta", "track_start", "track_stop", "x_from", "x_to",
            "weighting", "sound_weighting")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            steps = _apply_orderaps_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# Order complex (특정 차수 magnitude vs RPM). Same setup as Order APS but
# Pdtype "Order complex" + Datentyp.Order (the order to extract, e.g. 2) +
# Pdtypar "Magnitude". The X-axis here is RPM (not order), so it is ALWAYS reset
# to auto (Min/Max = "-") to clear any leftover order-axis range from an Order APS.
# --------------------------------------------------------------------------- #
def _apply_ordercomplex_row(row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction=None, quantity=None,
    order=None, blocksize=None, max_order=None,
    rpm_position=None, rpm_direction=None, rpm_quantity=None,
    delta=None, track_start=None, track_stop=None, weighting=None, sound_weighting="A"):
    """Configure one row as Order complex (single-order magnitude vs RPM) on $gd."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: Order complex ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(direction), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": direction, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Throughput"))
    _ev("$dt Srate %s" % _brace("32768"))
    _ev("$dt Pdtype %s" % _brace("Order complex"))
    _ev("$dt Pdtypar %s" % _brace("Magnitude"))
    _bs = blocksize if blocksize is not None else "2048"
    _ev("$dt Tp2spec_blocksize %s" % _brace(_bs)); steps["blocksize"] = _bs
    _mo = max_order if max_order is not None else "100"
    _ev("$dt Tp2spec_maxorder %s" % _brace(_mo)); steps["max_order"] = _mo
    _ordnum = order if order is not None else "2"
    _ev("$dt Order %s" % _brace(_ordnum)); steps["order"] = _ordnum
    steps["measurement_data_type"] = "Throughput"
    steps["graphic_data_type"] = "Order complex"
    steps["sampling_rate"] = "32768"
    steps["par"] = "Magnitude"
    _ev("catch {release $dt}; unset dt")
    # --- Frequency weighting (sound ALWAYS A-weighted) via Item.DarstFilter.Fweight ---
    _emit_sound_fweight(quantity, weighting, sound_weighting, steps)
    # --- Track parameter: RPM channel + Delta ---
    _ev("set tp [$it TrackingParams]")
    _rq = rpm_quantity or "Rotational Speed"
    _ev("$tp SetChanposTrack %s %s %s" % (_brace(rpm_position), _brace(rpm_direction), _brace(_rq)))
    steps["track_rpm_channel"] = {"position": rpm_position, "direction": rpm_direction, "quantity": _rq}
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    _dl = delta if delta is not None else "25"
    _ev("$tp Delta %s" % _brace(_dl)); steps["delta"] = _dl
    _ev("catch {release $tp}; unset tp")
    # --- X-axis (RPM): ALWAYS reset to auto (Min/Max = "-") ---
    _ev("set sd [$it SkalenDefinition]")
    _ev("set ax [$sd AchsenSkalierung]")
    _ev("$ax Aktiv1_ 1"); _ev("$ax Type1_ %s" % _brace("lin"))
    _ev("$ax Von1_ %s" % _brace("OFF")); _ev("$ax Bis1_ %s" % _brace("OFF"))
    steps["x_axis"] = "auto (Min/Max reset)"
    _ev("catch {release $ax}; unset ax")
    _ev("catch {release $sd}; unset sd")
    _ev("catch {release $it}; unset it")
    return steps


@mcp.tool()
def configure_ordercomplex_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
    measurement: str = "", position: str = "", direction: str = "", quantity: str = "",
    order: str = "2", blocksize: str = "2048", max_order: str = "100",
    rpm_position: str = "", rpm_direction: str = "S", rpm_quantity: str = "Rotational Speed",
    delta: str = "25", track_start: str = "Min", track_stop: str = "Max",
    output: bool = False) -> dict:
    """Configure one ORDER COMPLEX (특정 차수 magnitude vs RPM) row, then optionally
    run Graphic Output.

    Same tracking setup as Order APS but Graphic data type 'Order complex' with a
    specific Order number (default 2) extracted as Magnitude vs RPM. Fixed:
    Throughput, Srate 32768, Max order 100. Blocksize 2048 (variable). RPM track
    channel (Quantity 'Rotational Speed') + Delta. The X-axis (RPM) is ALWAYS reset
    to auto (Min/Max = "-") so a leftover Order-APS order-range does not stick.

    Args:
        order: the order to extract (Datentyp.Order), e.g. 2.
        position/direction/quantity: MEASURED channel.
        rpm_position/rpm_direction/rpm_quantity: RPM track channel.
        blocksize/max_order/delta: as Order APS.
    """
    try:
        _open_gd()
        steps = _apply_ordercomplex_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or None, quantity=quantity or None,
            order=order or None, blocksize=blocksize or None, max_order=max_order or None,
            rpm_position=rpm_position or None, rpm_direction=rpm_direction or None,
            rpm_quantity=rpm_quantity or None, delta=delta or None,
            track_start=track_start, track_stop=track_stop)
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_ordercomplex_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY ORDER COMPLEX rows in ONE COM session, then run Graphic Output.

    Each row object: row plus any of active/diagram/curve/measurement/position/
    direction/quantity/order/blocksize/max_order/rpm_position/rpm_direction/
    rpm_quantity/delta/track_start/track_stop. Fixed per row: Throughput, 32768,
    Pdtype 'Order complex', Par Magnitude, Max order 100, Blocksize 2048, Order 2
    (unless overridden). X-axis (RPM) always reset to auto. Non-RMS -> standard.vas_dly.
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "order", "blocksize", "max_order", "rpm_position",
            "rpm_direction", "rpm_quantity", "delta", "track_start", "track_stop",
            "weighting", "sound_weighting")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            steps = _apply_ordercomplex_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# Octave / 1/3-Octave (소음 표준 스펙트럼). Datentyp Pdtype "Octave" + Pdtypar
# (the only real variable: "1/1","1/3","1/6","1/12","1/24"). Srate = "Original"
# (NOT 32768). Freq. weighting = Tp2oct_fweight (sound -> "A"). Track = Time with
# Stat. parameter Average [Q] (REQUIRED -> 2D; 3D is rarely used). Start/Stop freq,
# average mode, time constant keep their Octave defaults (not exposed).
# --------------------------------------------------------------------------- #
def _apply_octave_row(row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction=None, quantity=None,
    fraction=None, weighting=None, sound_weighting="A",
    stat_parameter="Average [Q]", delta=None, track_start=None, track_stop=None):
    """Configure one row as a 1/3 (or 1/N) Octave analysis on an already-open $gd."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: Octave ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(direction), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": direction, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Throughput"))
    _ev("$dt Srate %s" % _brace("Original"))
    _ev("$dt Pdtype %s" % _brace("Octave"))
    _frac = fraction if fraction else "1/3"
    _ev("$dt Pdtypar %s" % _brace(_frac)); steps["fraction"] = _frac
    # frequency weighting (octave uses Tp2oct_fweight); auto-A for sound
    _wt = weighting
    if not _wt:
        _q = (quantity or "").lower()
        if sound_weighting and ("sound" in _q or "pressure" in _q):
            _wt = sound_weighting
    if _wt and _wt.lower() != "lin":
        try:
            _ev("$dt Tp2oct_fweight %s" % _brace(_wt)); steps["weighting"] = _wt
        except Exception:
            pass
    else:
        steps["weighting"] = "lin"
    steps["measurement_data_type"] = "Throughput"
    steps["graphic_data_type"] = "Octave"
    steps["sampling_rate"] = "Original"
    _ev("catch {release $dt}; unset dt")
    # --- Track parameter: Time track + Average [Q] (2D) ---
    _ev("set tp [$it TrackingParams]")
    _ev("$tp SetChanposTrack {} {} %s" % _brace("Time"))
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    _dl = delta if delta is not None else "0.25"
    try:
        _ev("$tp Delta %s" % _brace(_dl)); steps["delta"] = _dl
    except Exception:
        pass
    if stat_parameter and stat_parameter != "-":
        _tok = STAT_MAP.get(stat_parameter, stat_parameter)
        _ev("$tp Stats %s" % _brace(_tok)); steps["stat_parameter"] = stat_parameter
    _ev("catch {release $tp}; unset tp")
    _ev("catch {release $it}; unset it")
    return steps


@mcp.tool()
def configure_octave_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
    measurement: str = "", position: str = "", direction: str = "", quantity: str = "",
    fraction: str = "1/3", weighting: str = "", sound_weighting: str = "A",
    stat_parameter: str = "Average [Q]", delta: str = "0.25",
    track_start: str = "Min", track_stop: str = "Max", output: bool = False) -> dict:
    """Configure one OCTAVE / 1/3-octave (소음 표준 스펙트럼) row, then optionally output.

    Fixed: Measurement Throughput, Sampling rate "Original", Pdtype "Octave". The only
    real variable is `fraction` (Pdtypar): "1/1","1/3"(default),"1/6","1/12","1/24".
    Track = Time with Stat. parameter Average [Q] (REQUIRED -> 2D). Sound channels are
    auto A-weighted (Tp2oct_fweight); pass weighting="A"/"B"/"C"/"lin" to force.
    Start/Stop freq, average mode, time constant keep Octave defaults.
    """
    try:
        _open_gd()
        steps = _apply_octave_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or None, quantity=quantity or None,
            fraction=fraction or None, weighting=weighting or None,
            sound_weighting=sound_weighting, stat_parameter=stat_parameter,
            delta=delta or None, track_start=track_start, track_stop=track_stop)
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_octave_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY OCTAVE rows in ONE COM session, then run Graphic Output.

    Each row object: row plus any of active/diagram/curve/measurement/position/
    direction/quantity/fraction/weighting/sound_weighting/stat_parameter/delta/
    track_start/track_stop. Fixed: Throughput, Srate "Original", Pdtype "Octave",
    Average [Q] (2D). fraction default "1/3". Sound auto A-weighted. Non-RMS ->
    standard.vas_dly layout. Overlay several channels in one diagram to compare.
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "fraction", "weighting", "sound_weighting", "stat_parameter",
            "delta", "track_start", "track_stop")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            steps = _apply_octave_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# Overall / Sum level (OA, 전대역 단일 레벨 vs 트랙축). Datentyp Pdtype "Sum level"
# + Tp2spec_blocksize. Track can be TIME-based (Delta = seconds, e.g. 0.125) OR a
# VALUE channel (RPM / Speed / Torque; Delta = that unit's step, e.g. 30 RPM).
# CRITICAL: for a value track, Delta is in the track's units. Leaving a time-step
# like 0.125 on an RPM track means "0.125 RPM steps" -> huge point count -> PAK can
# hang/crash. The tool guards this: value track + no delta -> safe default (30 for
# RPM-like); RPM-like + delta<1 -> warn and bump to a safe value.
# Sound channels are auto A-weighted (Item.DarstFilter.Fweight). Non-RMS layout.
# --------------------------------------------------------------------------- #
def _apply_overall_row(row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction=None, quantity=None, blocksize=None,
    track_position=None, track_direction=None, track_quantity=None,
    delta=None, track_start=None, track_stop=None,
    weighting=None, sound_weighting="A"):
    """Configure one row as an Overall / Sum level analysis on an already-open $gd."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: Overall / Sum level ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(direction), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": direction, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Throughput"))
    _ev("$dt Srate %s" % _brace("32768"))
    # The Overall-level PlotDtype token varies by PAK build: current builds expose it
    # as "Overall" (older ones as "Sum level"), and only ONE is in the filtered
    # selection list. Try each; keep whichever the build accepts.
    _oa_tok = None
    for _cand in ("Overall", "Sum level"):
        try:
            _ev("$dt Pdtype %s" % _brace(_cand))
            _oa_tok = _cand
            break
        except Exception:
            continue
    _bs = blocksize if blocksize is not None else "16384"
    _ev("$dt Tp2spec_blocksize %s" % _brace(_bs)); steps["blocksize"] = _bs
    steps["measurement_data_type"] = "Throughput"
    steps["graphic_data_type"] = _oa_tok or "Overall"
    steps["sampling_rate"] = "32768"
    _ev("catch {release $dt}; unset dt")
    # --- Frequency weighting (sound -> A) via Item.DarstFilter.Fweight ---
    _wt = weighting
    if not _wt:
        _q = (quantity or "").lower()
        if sound_weighting and ("sound" in _q or "pressure" in _q):
            _wt = sound_weighting
    if _wt and _wt.lower() != "lin":
        _ev("set df [$it DarstFilter]")
        try:
            _ev("$df Fweight %s" % _brace(_wt)); steps["weighting"] = _wt
        except Exception:
            pass
        _ev("catch {release $df}; unset df")
    else:
        steps["weighting"] = "lin"
    # --- Track parameter: Time-based OR value(RPM/Speed/Torque)-based ---
    _ev("set tp [$it TrackingParams]")
    if track_quantity:  # value track
        _rq = track_quantity
        _ev("$tp SetChanposTrack %s %s %s" % (_brace(track_position),
            _brace(track_direction if track_direction is not None else "S"), _brace(_rq)))
        steps["track"] = {"mode": "value", "position": track_position,
                          "direction": track_direction, "quantity": _rq}
        _rpmlike = any(w in _rq.lower() for w in ("rot", "rpm", "speed"))
        _dl = delta
        _num = None
        try:
            _num = float(_dl) if _dl is not None else None
        except Exception:
            _num = None
        if _dl is None:
            _dl = "30" if _rpmlike else "1"
            steps["delta_note"] = "value-track: no delta -> defaulted to %s (%s)" % (_dl, _rq)
        elif _rpmlike and _num is not None and _num < 1:
            steps["delta_warning"] = ("value-track delta %s < 1 in RPM units (time-step leftover?) "
                                      "-> bumped to 30 to avoid a hang/crash" % _dl)
            _dl = "30"
    else:               # time track
        _ev("$tp SetChanposTrack {} {} %s" % _brace("Time"))
        steps["track"] = {"mode": "time", "quantity": "Time"}
        _dl = delta if delta is not None else "0.125"
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    _ev("$tp Delta %s" % _brace(_dl)); steps["delta"] = _dl
    _ev("catch {release $tp}; unset tp")
    _ev("catch {release $it}; unset it")
    return steps


@mcp.tool()
def configure_overall_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
    measurement: str = "", position: str = "", direction: str = "", quantity: str = "",
    blocksize: str = "16384",
    track_position: str = "", track_direction: str = "S", track_quantity: str = "",
    delta: str = "", track_start: str = "Min", track_stop: str = "Max",
    weighting: str = "", sound_weighting: str = "A", output: bool = False) -> dict:
    """Configure one OVERALL / Sum level (OA) row, then optionally run Graphic Output.

    Overall level vs a track axis. Fixed: Throughput, Srate 32768, Pdtype "Sum level",
    Blocksize 16384. TWO track modes:
      * TIME-based (default, leave track_quantity empty): Delta = seconds (default 0.125).
      * VALUE-based: set track_quantity ("Rotational Speed"/"Speed"/"Torque") +
        track_position/track_direction. Delta = that unit's step (e.g. 30 for RPM).

    CRITICAL delta rule: on a value track, Delta is in the track's units. A leftover
    time-step like 0.125 on an RPM track = 0.125-RPM steps -> huge point count -> PAK
    can hang. This tool guards it: value-track + no delta -> 30 (RPM-like); RPM-like +
    delta<1 -> warns and bumps to 30. Sound channels auto A-weighted.
    """
    try:
        _open_gd()
        steps = _apply_overall_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or None, quantity=quantity or None,
            blocksize=blocksize or None,
            track_position=track_position or None, track_direction=track_direction or None,
            track_quantity=track_quantity or None, delta=(delta if delta != "" else None),
            track_start=track_start, track_stop=track_stop,
            weighting=weighting or None, sound_weighting=sound_weighting)
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_overall_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY OVERALL / Sum level rows in ONE COM session, then Graphic Output.

    Each row object: row plus any of active/diagram/curve/measurement/position/
    direction/quantity/blocksize/track_position/track_direction/track_quantity/delta/
    track_start/track_stop/weighting/sound_weighting. Time track by default; set
    track_quantity for a value(RPM/Speed/Torque) track. Value-track Delta is guarded
    against tiny time-step leftovers (see configure_overall_row). Sound auto A-weighted.
    Non-RMS -> standard.vas_dly layout.
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "blocksize", "track_position", "track_direction",
            "track_quantity", "delta", "track_start", "track_stop",
            "weighting", "sound_weighting")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            steps = _apply_overall_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# CAN / Slow-quantity signals (RPM, Torque, SOC, vehicle speed, ... from the CAN
# bus). These are ALWAYS 2D (value vs Time) with NO averaging -- distinct from
# APS / Octave / Order. Datentyp Mdtype "Slow throughput" + Pdtype "Slow quantity",
# Srate "Original". Track parameter = Time (Min..Max), no Stat parameter. X (time)
# and Y (value) axes are reset to auto so the real range shows (e.g. RPM ~0..15000),
# NOT the default 20..140. No blocksize / order / RPM-track / weighting.
# --------------------------------------------------------------------------- #
def _apply_can_row(row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction=None, quantity=None,
    track_start=None, track_stop=None):
    """Configure one row as a CAN Slow-quantity signal (value vs Time) on $gd."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: Slow throughput -> Slow quantity (2D, no average) ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _dir = direction if direction is not None else "S"
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(_dir), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": _dir, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Slow throughput"))
    _ev("$dt Srate %s" % _brace("Original"))
    _ev("$dt Pdtype %s" % _brace("Slow quantity"))
    steps["measurement_data_type"] = "Slow throughput"
    steps["graphic_data_type"] = "Slow quantity"
    steps["sampling_rate"] = "Original"
    _ev("catch {release $dt}; unset dt")
    # --- Track parameter: Time (no averaging for CAN) ---
    _ev("set tp [$it TrackingParams]")
    _ev("$tp SetChanposTrack {} {} %s" % _brace("Time"))
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    steps["track"] = {"quantity": "Time",
                      "start": track_start if track_start is not None else "Min",
                      "stop": track_stop if track_stop is not None else "Max"}
    _ev("catch {release $tp}; unset tp")
    # --- X (time) + Y (value) axes -> auto so RPM/Torque scale to the data ---
    _ev("set sd [$it SkalenDefinition]")
    _ev("set ax [$sd AchsenSkalierung]")
    _ev("$ax Aktiv1_ 1"); _ev("$ax Type1_ %s" % _brace("lin"))
    _ev("$ax Von1_ %s" % _brace("OFF")); _ev("$ax Bis1_ %s" % _brace("OFF"))
    _ev("$ax Aktiv2_ 1"); _ev("$ax Type2_ %s" % _brace("lin"))
    _ev("$ax Von2_ %s" % _brace("OFF")); _ev("$ax Bis2_ %s" % _brace("OFF"))
    steps["x_axis"] = "auto (time)"
    steps["y_axis"] = "auto (value)"
    _ev("catch {release $ax}; unset ax")
    _ev("catch {release $sd}; unset sd")
    _ev("catch {release $it}; unset it")
    return steps


@mcp.tool()
def configure_can_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
    measurement: str = "", position: str = "", direction: str = "S", quantity: str = "",
    track_start: str = "Min", track_stop: str = "Max", output: bool = False) -> dict:
    """Configure one CAN (Slow-quantity) row -- a CAN-bus signal (RPM, Torque, SOC,
    vehicle speed, ...) drawn as value vs TIME, then optionally run Graphic Output.

    CAN signals are ALWAYS 2D with NO averaging. Fixed per row: Measurement data
    type 'Slow throughput', Graphic data type 'Slow quantity', Sampling rate
    'Original', Track parameter = Time (Min..Max). X (time) and Y (value) axes are
    reset to auto so the real value range shows (e.g. RPM ~0..15000), not the default
    20..140. No blocksize / order / RPM-track / averaging.

    Args:
        position/direction/quantity: the CAN channel, e.g. CH65 / S / Rotational Speed
            or CH66 / S / Torque. direction is usually 'S'.
        diagram/curve: put each CAN quantity in its own diagram; overlay runs as curves.
    """
    try:
        _open_gd()
        steps = _apply_can_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or None, quantity=quantity or None,
            track_start=track_start, track_stop=track_stop)
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_can_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY CAN (Slow-quantity) rows in ONE COM session, then Graphic Output.

    Each row object: row plus any of active/diagram/curve/measurement/position/
    direction/quantity/track_start/track_stop. Fixed per row: Slow throughput ->
    Slow quantity, Srate Original, Track = Time (Min..Max), NO averaging, X/Y axes
    auto. Put each CAN quantity (e.g. CH65 Rotational Speed, CH66 Torque) in its own
    diagram and overlay the measurements as curves. Non-RMS -> standard.vas_dly layout.

    Example row:
      {"row":1,"diagram":1,"curve":1,"measurement":"ENG_01/Test_01 [CP]",
       "position":"CH65","direction":"S","quantity":"Rotational Speed"}
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "track_start", "track_stop")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            steps = _apply_can_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# Detector (레벨 vs 트랙축; 정속/패스바이 외부소음에 주로 씀). Datentyp Pdtype
# "Detector" + Tp2det_type ("rms"/"peak"/...) + Tp2det_fweight (sound -> "A").
# Track is usually DISTANCE-based for pass-by: Par-Channel = Cart. Coord.x /
# Distance, Start -10 .. Stop 20 m, Delta 0.25 m. (Also works with Time / RPM.)
# The distance quantity reads back as "Cart. coord.x"; SetChanposTrack is tried
# with a couple of casings. Non-RMS -> standard.vas_dly layout.
# --------------------------------------------------------------------------- #
def _apply_detector_row(row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction=None, quantity=None,
    detector_type=None, weighting=None, sound_weighting="A",
    track_position=None, track_direction=None, track_quantity=None,
    track_start=None, track_stop=None, delta=None):
    """Configure one row as a Detector analysis (default: distance-track) on $gd."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: Detector ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(direction), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": direction, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Throughput"))
    _ev("$dt Srate %s" % _brace("32768"))
    _ev("$dt Pdtype %s" % _brace("Detector"))
    _dtype = detector_type if detector_type else "rms"
    _ev("$dt Tp2det_type %s" % _brace(_dtype)); steps["detector_type"] = _dtype
    # frequency weighting (Detector's own field = Tp2det_fweight); sound -> A
    _wt = weighting
    if not _wt:
        _q = (quantity or "").lower()
        if sound_weighting and ("sound" in _q or "pressure" in _q):
            _wt = sound_weighting
    if _wt and _wt.lower() != "lin":
        try:
            _ev("$dt Tp2det_fweight %s" % _brace(_wt)); steps["weighting"] = _wt
        except Exception:
            pass
    else:
        steps["weighting"] = "lin"
    steps["measurement_data_type"] = "Throughput"
    steps["graphic_data_type"] = "Detector"
    steps["sampling_rate"] = "32768"
    _ev("catch {release $dt}; unset dt")
    # --- Track parameter ---
    _ev("set tp [$it TrackingParams]")
    if track_quantity:
        # try candidate quantity spellings; VERIFY via Trackquantity read-back that
        # the track actually became the value channel (no exception != took effect).
        # Try the caller's quantity FIRST. Only the distance quantity has a casing
        # trap ("Cart. Coord.x" -> Error; "Cart. coord.x" works), so add those
        # variants ONLY when the quantity is the Cartesian-coordinate one. For any
        # other track (Driving Speed, Rotational Speed, Torque, ...) use it verbatim.
        _cands = [track_quantity]
        if "coord" in track_quantity.lower():
            for _q in ("Cart. coord.x", "Cart. Coord.x"):
                if _q not in _cands:
                    _cands.append(_q)
        _tqd = _brace(track_direction if track_direction is not None else "S")
        _applied = None
        for _q in _cands:
            try:
                _ev("$tp SetChanposTrack %s %s %s" % (_brace(track_position), _tqd, _brace(_q)))
            except Exception:
                continue
            try:
                _cur = _ev("$tp Trackquantity")
            except Exception:
                _cur = ""
            _lc = str(_cur).lower()
            if _cur and "time" not in _lc and "error" not in _lc:
                _applied = _cur
                break
        steps["track"] = {"position": track_position, "direction": track_direction,
                          "quantity": _applied or "(NOT set - still Time?)"}
    else:
        _ev("$tp SetChanposTrack {} {} %s" % _brace("Time"))
        steps["track"] = {"quantity": "Time"}
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    _dl = delta if delta is not None else "0.25"
    _ev("$tp Delta %s" % _brace(_dl)); steps["delta"] = _dl
    _ev("catch {release $tp}; unset tp")
    _ev("catch {release $it}; unset it")
    return steps


# Named track presets for exterior-noise Detector (so other windows can pick a track
# with ONE arg without knowing the exact channel/quantity/range strings).
_DETECTOR_TRACK_PRESETS = {
    "distance": {"track_position": "Distance", "track_direction": "S",
                 "track_quantity": "Cart. coord.x", "track_start": "-10",
                 "track_stop": "20", "delta": "0.25"},   # 정속/pass-by, metres
    "speed":    {"track_position": "Speed", "track_direction": "S",
                 "track_quantity": "Driving Speed", "track_start": "40",
                 "track_stop": "60", "delta": "0.25"},    # 가속, km/h (e.g. Vbox GPS)
    "time":     {"track_position": "", "track_direction": "S",
                 "track_quantity": "", "track_start": "Min",
                 "track_stop": "Max", "delta": "0.125"},   # time track, seconds
}


def _resolve_detector_track(track_preset, track_position, track_direction,
                            track_quantity, track_start, track_stop, delta):
    """Merge a named preset (distance/speed/time) with any explicit overrides
    (non-empty explicit value wins)."""
    p = _DETECTOR_TRACK_PRESETS.get((track_preset or "distance").lower(),
                                    _DETECTOR_TRACK_PRESETS["distance"])
    def pick(v, key):
        return v if (v not in (None, "")) else p[key]
    return {
        "track_position": pick(track_position, "track_position"),
        "track_direction": pick(track_direction, "track_direction"),
        # track_quantity == "" is meaningful (Time), so only fall back when None
        "track_quantity": track_quantity if track_quantity not in (None,) else p["track_quantity"],
        "track_start": pick(track_start, "track_start"),
        "track_stop": pick(track_stop, "track_stop"),
        "delta": pick(delta, "delta"),
    }


@mcp.tool()
def configure_detector_row(row: int, active: bool = True, diagram: int = 1, curve: int = 1,
    measurement: str = "", position: str = "", direction: str = "", quantity: str = "",
    detector_type: str = "rms", weighting: str = "", sound_weighting: str = "A",
    track_preset: str = "distance",
    track_position: str = "", track_direction: str = "", track_quantity: str = "",
    track_start: str = "", track_stop: str = "", delta: str = "",
    output: bool = False) -> dict:
    """Configure one DETECTOR row (외부소음: 정속/패스바이 or 가속), then optionally output.

    Detector level (rms/peak/...) vs a track axis. Fixed: Throughput, Srate 32768,
    Pdtype "Detector". Sound channels auto A-weighted (Tp2det_fweight).

    Pick the track with ONE arg via `track_preset` (explicit track_* args override):
      * "distance" (DEFAULT, 정속/pass-by): Par.-Channel Distance / Cart. coord.x,
        Start -10, Stop 20 m, Delta 0.25.
      * "speed" (가속): Par.-Channel Speed / Driving Speed (e.g. Vbox GPS),
        Start 40, Stop 60 km/h, Delta 0.25.
      * "time": Time track, Min..Max, Delta 0.125 s.
    For any other value track (RPM/Torque) pass track_quantity="Rotational Speed" etc.

    Args:
        detector_type: "rms" (default), "peak", ... (Tp2det_type).
        track_preset: "distance" | "speed" | "time".
        track_position/track_direction/track_quantity/track_start/track_stop/delta:
            explicit overrides (leave "" to use the preset).
    """
    tr = _resolve_detector_track(track_preset, track_position, track_direction,
                                 track_quantity, track_start, track_stop, delta)
    try:
        _open_gd()
        steps = _apply_detector_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or None, quantity=quantity or None,
            detector_type=detector_type or None, weighting=weighting or None,
            sound_weighting=sound_weighting,
            track_position=tr["track_position"] or None,
            track_direction=tr["track_direction"] or None,
            track_quantity=(tr["track_quantity"] if tr["track_quantity"] != "" else None),
            track_start=tr["track_start"], track_stop=tr["track_stop"], delta=tr["delta"])
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_detector_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Configure MANY DETECTOR rows in ONE COM session, then run Graphic Output.

    Each row object: row plus any of active/diagram/curve/measurement/position/
    direction/quantity/detector_type/weighting/sound_weighting/**track_preset**/
    track_position/track_direction/track_quantity/track_start/track_stop/delta.
    Pick the track with ONE key: `"track_preset": "distance"` (default, 정속/pass-by,
    Cart. coord.x -10..20) / "speed" (가속, Driving Speed 40..60) / "time". Explicit
    track_* override the preset. Sound auto A-weighted. Non-RMS -> standard.vas_dly.
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "detector_type", "weighting", "sound_weighting")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            kw.setdefault("detector_type", "rms")
            tr = _resolve_detector_track(
                rr.get("track_preset", "distance"),
                rr.get("track_position", ""), rr.get("track_direction", ""),
                rr.get("track_quantity", None),
                rr.get("track_start", ""), rr.get("track_stop", ""), rr.get("delta", ""))
            kw["track_position"] = tr["track_position"] or None
            kw["track_direction"] = tr["track_direction"] or None
            kw["track_quantity"] = (tr["track_quantity"] if tr["track_quantity"] != "" else None)
            kw["track_start"] = tr["track_start"]
            kw["track_stop"] = tr["track_stop"]
            kw["delta"] = tr["delta"]
            steps = _apply_detector_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# CHAINED PIPELINE.  run_analysis collapses reset -> configure many rows (mixed
# analysis families) -> layout -> Graphic Output -> screenshot -> server-side
# verification into ONE MCP call / one COM session. This is the "workflow
# chaining" step: it removes the per-step LLM round-trips (the dominant cost of
# a multi-analysis request) and folds the readback checks in, so the LLM only
# needs to Read the final screenshot.
# --------------------------------------------------------------------------- #
@mcp.tool()
def run_analysis(rows: str, layout: str = "standard.vas_dly",
                 deactivate_beyond: int = 0, capture: bool = True,
                 capture_path: str = "C:/MCPProject_pak/view_shot.png",
                 inline_capture: bool = False):
    """CHAINED analysis pipeline in ONE call: configure many rows (families may be
    mixed across rows) -> apply layout -> Graphic Output -> screenshot ->
    server-side verification. Replaces the sequence reset_graphdef +
    configure_*_rows + graphic_output + capture_viewer with a single round-trip.

    rows: JSON list. Each object needs "row" (1-based) and "analysis", plus that
    family's params:
      analysis="aps"          -> position/direction/quantity + measurement (+ optional
                                 sampling_rate/blocksize/x_from/x_to). Defaults:
                                 measurement_data_type="Throughput", graphic_data_type="APS".
      analysis="octave"       -> ...+ fraction (e.g. "1/3"); stat_parameter default "Average [Q]".
      analysis="overall"      -> full level vs time/RPM; track_position/track_quantity + delta.
      analysis="orderaps"     -> ...+ max_order, rpm_position/rpm_direction/rpm_quantity, delta.
      analysis="ordercomplex" -> ...+ order, max_order, rpm_*.
      analysis="detector"     -> exterior LH/RH; pick the track with ONE key
                                 "track_preset": "distance"(default,정속/pass-by) /
                                 "speed"(가속) / "time". Explicit track_* override it.
    Sound Pressure channels are ALWAYS A-weighted automatically; vibration stays
    linear. Band-pass RMS tables are NOT handled here -- use output_rms (it owns the
    RMS.vas_dly layout + sum-level table). layout="none" skips the layout step.
    inline_capture=True embeds the screenshot in the response (base64) so it shows
    directly in chat -- use when the client can't open the saved capture path.

    Returns: per-row `applied` steps, a `verification` list (weighting + resolved
    track per row) with `warnings` (sound not A-weighted, track fell back to Time),
    and `capture` path -- Read that PNG for the final visual check.
    """
    data = json.loads(rows) if isinstance(rows, str) else rows

    APS_KEYS = ("active", "diagram", "curve", "measurement", "position", "direction",
                "quantity", "measurement_data_type", "graphic_data_type", "sampling_rate",
                "blocksize", "track_quantity", "track_position", "track_direction",
                "track_start", "track_stop", "weighting", "stat_parameter",
                "x_from", "x_to", "x_type", "y_type", "y_from", "y_to")
    OCT_KEYS = ("active", "diagram", "curve", "measurement", "position", "direction",
                "quantity", "fraction", "weighting", "sound_weighting", "stat_parameter",
                "delta", "track_start", "track_stop")
    OA_KEYS = ("active", "diagram", "curve", "measurement", "position", "direction",
               "quantity", "blocksize", "track_position", "track_direction",
               "track_quantity", "delta", "track_start", "track_stop", "weighting",
               "sound_weighting")
    OAPS_KEYS = ("active", "diagram", "curve", "measurement", "position", "direction",
                 "quantity", "blocksize", "max_order", "rpm_position", "rpm_direction",
                 "rpm_quantity", "delta", "track_start", "track_stop", "x_from", "x_to",
                 "weighting", "sound_weighting")
    OCX_KEYS = OAPS_KEYS + ("order",)
    DET_KEYS = ("active", "diagram", "curve", "measurement", "position", "direction",
                "quantity", "detector_type", "weighting", "sound_weighting")

    try:
        _open_gd(visible=True)   # _open_gd() resets lingering COM handles first
        results = []
        listed = set()
        for r in data:
            rr = dict(r)
            rownum = int(rr.get("row"))
            listed.add(rownum)
            fam = str(rr.get("analysis", "aps")).lower().replace(" ", "").replace("_", "")
            if fam in ("aps", "fft", "2daps", "3daps"):
                kw = {k: rr.get(k) for k in APS_KEYS if k in rr}
                kw.setdefault("active", True)
                kw.setdefault("measurement_data_type", "Throughput")
                kw.setdefault("graphic_data_type", "APS")
                steps = _apply_row(rownum, **kw)
            elif fam in ("octave", "oct", "1/3octave", "1/1octave"):
                kw = {k: rr.get(k) for k in OCT_KEYS if k in rr}
                kw.setdefault("active", True)
                steps = _apply_octave_row(rownum, **kw)
            elif fam in ("overall", "oa", "sumlevel"):
                kw = {k: rr.get(k) for k in OA_KEYS if k in rr}
                kw.setdefault("active", True)
                steps = _apply_overall_row(rownum, **kw)
            elif fam in ("orderaps", "order"):
                kw = {k: rr.get(k) for k in OAPS_KEYS if k in rr}
                kw.setdefault("active", True)
                steps = _apply_orderaps_row(rownum, **kw)
            elif fam in ("ordercomplex",):
                kw = {k: rr.get(k) for k in OCX_KEYS if k in rr}
                kw.setdefault("active", True)
                steps = _apply_ordercomplex_row(rownum, **kw)
            elif fam in ("detector", "det", "exterior"):
                kw = {k: rr.get(k) for k in DET_KEYS if k in rr}
                kw.setdefault("active", True)
                kw.setdefault("detector_type", "rms")
                tr = _resolve_detector_track(
                    rr.get("track_preset", "distance"),
                    rr.get("track_position", ""), rr.get("track_direction", ""),
                    rr.get("track_quantity", None),
                    rr.get("track_start", ""), rr.get("track_stop", ""), rr.get("delta", ""))
                kw["track_position"] = tr["track_position"] or None
                kw["track_direction"] = tr["track_direction"] or None
                kw["track_quantity"] = (tr["track_quantity"] if tr["track_quantity"] != "" else None)
                kw["track_start"] = tr["track_start"]
                kw["track_stop"] = tr["track_stop"]
                kw["delta"] = tr["delta"]
                steps = _apply_detector_row(rownum, **kw)
            elif fam in ("rms", "bandrms"):
                results.append({"row": rownum, "analysis": fam,
                                "error": "RMS 밴드표는 output_rms 도구를 쓰세요 (RMS.vas_dly + 표)."})
                continue
            else:
                results.append({"row": rownum, "analysis": fam,
                                "error": "unknown analysis '%s'" % fam})
                continue
            results.append({"row": rownum, "analysis": fam, "applied": steps})
            # progress sidecar: lets a long/timed-out call be observed + confirmed
            try:
                _pf = os.path.join(os.path.dirname(capture_path) or ".", "run_analysis_progress.json")
                with open(_pf, "w", encoding="utf-8") as _fh:
                    json.dump({"configured_rows": len(results), "total": len(data),
                               "last_row": rownum, "done": False}, _fh, ensure_ascii=False)
            except Exception:
                pass

        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")

        if layout and str(layout).lower() not in ("none", ""):
            _apply_layout(layout, _STD_LAYOUT_TEMPLATE)
        _ev("$gd Graphicoutput")

        # ---- server-side verification (readback echoes already inside steps) ----
        verification = []
        warnings = []
        for res in results:
            st = res.get("applied")
            if not isinstance(st, dict):
                continue
            wt = st.get("weighting")
            track = st.get("track") if isinstance(st.get("track"), dict) else {}
            tq = track.get("quantity")
            ch = st.get("channel") if isinstance(st.get("channel"), dict) else {}
            q = (ch.get("quantity") or "").lower()
            verification.append({"row": res["row"], "analysis": res["analysis"],
                                 "weighting": wt, "track_quantity": tq})
            if ("sound" in q or "pressure" in q) and wt and str(wt).lower() != "a":
                warnings.append("row %s: sound channel not A-weighted (got %r)" % (res["row"], wt))
            if isinstance(tq, str) and ("not set" in tq.lower() or "time?" in tq.lower()):
                warnings.append("row %s: track fell back (%s) -- check track_preset/quantity" % (res["row"], tq))

        out = {"ok": True, "rows": results, "verification": verification,
               "warnings": warnings, "deactivated_beyond": int(deactivate_beyond or 0),
               "layout": layout}
        _inline_img = None
        if capture and inline_capture:
            _inline_img, info = _capture_inline(capture_path)
            ok = _inline_img is not None
            out["capture_ok"] = bool(ok)
            out["capture"] = ({"path": capture_path, "inline": True} if ok else {"error": info})
            out["next"] = ("Inline screenshot attached to this response -- view it directly."
                           if ok else
                           "Read the screenshot at %s for the final visual check." % capture_path)
        elif capture:
            ok, info = _capture_viewer(capture_path)
            out["capture_ok"] = bool(ok)
            out["capture"] = info if ok else {"error": info}
            out["next"] = "Read the screenshot at %s for the final visual check." % capture_path
        # result sidecar: written even if the MCP client already timed out (PAK finishes
        # regardless), so a big single call can be confirmed by reading this file + the PNG.
        try:
            import time as _time
            _rf = os.path.join(os.path.dirname(capture_path) or ".", "run_analysis_result.json")
            _payload = dict(out)
            _payload["timestamp"] = _time.strftime("%Y-%m-%d %H:%M:%S")
            _payload["done"] = True
            with open(_rf, "w", encoding="utf-8") as _fh:
                json.dump(_payload, _fh, ensure_ascii=False, indent=2)
            out["result_file"] = _rf
            _pf = os.path.join(os.path.dirname(capture_path) or ".", "run_analysis_progress.json")
            with open(_pf, "w", encoding="utf-8") as _fh:
                json.dump({"configured_rows": len(results), "total": len(results),
                           "last_row": (results[-1]["row"] if results else None), "done": True},
                          _fh, ensure_ascii=False)
        except Exception:
            pass
        # return [json, image] so the screenshot renders inline (no client file access);
        # plain dict when inline capture was not requested / not available.
        if _inline_img is not None:
            return [out, _inline_img]
        return out
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# RMS layout auto-generation.  AutoFormat folder = RMS value-table layouts
# (distinct from PlotEditor = analysis definitions). The RMS.vas_dly template is
# plain XML; we write it verbatim, optionally resizing the table font (Malgun
# Gothic, used only by the RMS table).
# --------------------------------------------------------------------------- #
_RMS_LAYOUT_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RMS.vas_dly")
_STD_LAYOUT_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standard.vas_dly")
_MALGUN = "맑은 고딕"   # Malgun Gothic (used only by the RMS table)


def _ensure_layout_in_autoformat(template_path, layout_name):
    """Copy a bundled .vas_dly template into <Tablepath>/AutoFormat if it is
    missing there. Requires an open $reference. Best-effort; returns target path."""
    try:
        tp = _ev("$reference Tablepath")
    except Exception:
        return None
    tgt = os.path.join(tp.replace("\\", "/"), "AutoFormat", layout_name)
    try:
        if template_path and os.path.exists(template_path) and not os.path.exists(tgt):
            with open(template_path, "rb") as fh:
                data = fh.read()
            os.makedirs(os.path.dirname(tgt), exist_ok=True)
            with open(tgt, "wb") as fh:
                fh.write(data)
    except Exception:
        pass
    return tgt


def _apply_layout(layout_name, template_path=None):
    """On an already-open $gd: force the output layout to `layout_name` via
    Optionen.Format="Autoformat" + Foname (auto-creating the file in AutoFormat from
    the bundled template if missing). Used to give non-RMS outputs the standard
    layout (standard.vas_dly) the way RMS uses RMS.vas_dly. Best-effort."""
    if template_path:
        _ensure_layout_in_autoformat(template_path, layout_name)
    try:
        _ev("set opt [$gd Optionen]")
        try:
            _ev("$opt Format %s" % _brace("Autoformat"))
        except Exception:
            pass
        try:
            _ev("$opt Foname %s" % _brace(layout_name))
        except Exception:
            pass
        _ev("catch {release $opt}; unset opt")
    except Exception:
        _ev("catch {release $opt}; unset opt")


def _rms_layout_xml(table_fontsize=0):
    """Return the RMS layout XML text, optionally with a resized table font."""
    with open(_RMS_LAYOUT_TEMPLATE, "rb") as fh:
        xml = fh.read().decode("utf-8")     # keeps CRLF as \r\n
    if table_fontsize and int(table_fontsize) > 0:
        n = int(table_fontsize)
        # table-cell fonts (HTML-escaped inside the <text>): only Malgun uses size 8
        xml = xml.replace("size=&quot;8&quot;", "size=&quot;%d&quot;" % n)
        # outer text-object font
        xml = xml.replace('<font family="%s" ptsize="9.0"/>' % _MALGUN,
                          '<font family="%s" ptsize="%d.0"/>' % (_MALGUN, n))
    return xml


def _write_rms_layout(target_path, table_fontsize=0):
    xml = _rms_layout_xml(table_fontsize)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "wb") as fh:
        fh.write(xml.encode("utf-8"))       # preserve CRLF/UTF-8
    return target_path


def _rms_layout_target():
    """Return <Tablepath>/AutoFormat/RMS.vas_dly (reads PAK Tablepath via COM)."""
    _ensure_sourced()
    _ev("set reference [createobject $pak_application]")
    tp = _ev("$reference Tablepath")
    _ev("catch {release $reference}; unset reference")
    return os.path.join(tp.replace("\\", "/"), "AutoFormat", "RMS.vas_dly")


@mcp.tool()
def ensure_rms_layout(table_fontsize: int = 0, force: bool = False) -> dict:
    """Create the RMS value-table layout (RMS.vas_dly) in PAK's AutoFormat folder,
    so users without the file can run output_rms. AutoFormat = RMS value tables
    (NOT PlotEditor, which holds analysis definitions).

    Args:
        table_fontsize: if > 0, set the RMS table font (Malgun Gothic) to this pt
            size (both the text-object and the table cells). Use smaller sizes when
            many diagrams shrink each table. 0 = keep original (9 pt / 8 pt cells).
        force: overwrite even if the file already exists.
    """
    if not os.path.exists(_RMS_LAYOUT_TEMPLATE):
        return {"ok": False, "error": "template missing: %s" % _RMS_LAYOUT_TEMPLATE}
    try:
        target = _rms_layout_target()
    except Exception as exc:
        return {"ok": False, "error": "could not read Tablepath: %s" % str(exc).splitlines()[0]}
    finally:
        _reset()
    exists = os.path.exists(target)
    if exists and not force and not table_fontsize:
        return {"ok": True, "created": False, "path": target, "note": "already exists"}
    _write_rms_layout(target, table_fontsize)
    return {"ok": True, "created": True, "path": target,
            "table_fontsize": int(table_fontsize) if table_fontsize else "original (9/8)"}


# --------------------------------------------------------------------------- #
# Output layout mode (GraphDef.Optionen.Fomode / Foname).
# The "Layout" dropdown in the Graphic Definition toolbar reads "None" until
# Fomode is set to "Variable" (which enables a user layout such as RMS.vas_dly).
# output_rms only sets Foname, so if a reset leaves Fomode="None" the RMS table
# is not drawn; call this to (re)enable it.
# --------------------------------------------------------------------------- #
def _try_get(cmd):
    try:
        return _ev(cmd)
    except Exception as exc:
        return "<err:%s>" % (str(exc).splitlines()[0][:40])


@mcp.tool()
def set_layout_mode(mode: str = "Autoformat", layout: str = "RMS.vas_dly") -> dict:
    """Enable a value-table layout via Optionen.Format + Optionen.Foname.

    Optionen.Foname (the layout file) is read-only UNLESS Optionen.Format is set to
    "Autoformat" first (that mode auto-applies a layout from the AutoFormat folder).
    So this sets Format="Autoformat" and then loads Foname -- fully from COM, no UI
    step. (The toolbar "Layout" None/Fix/Variable dropdown is UI-only and not the
    same thing; Format always reads "Auto"/"Autoformat".)

    Args:
        mode: Optionen.Format value ("Autoformat" enables auto-layout).
        layout: layout file to load into Optionen.Foname (e.g. "RMS.vas_dly").
            Pass "" to leave Foname unchanged.

    Returns before/after values read back from PAK so you can confirm it stuck.
    """
    try:
        _open_gd(visible=True)
        _ev("set opt [$gd Optionen]")
        before_fm = _try_get("$opt Format")
        before_fn = _try_get("$opt Foname")
        err_fm = None
        try:
            _ev("$opt Format %s" % _brace(mode))
        except Exception as exc:
            err_fm = str(exc).splitlines()[0]
        err_fn = None
        if layout:
            try:
                _ev("$opt Foname %s" % _brace(layout))
            except Exception as exc:
                err_fn = str(exc).splitlines()[0]
        after_fm = _try_get("$opt Format")
        after_fn = _try_get("$opt Foname")
        _ev("catch {release $opt}; unset opt")
        return {
            "ok": True,
            "format": {"before": before_fm, "requested": mode, "after": after_fm,
                       "error": err_fm, "changed": before_fm != after_fm},
            "foname": {"before": before_fn, "requested": (layout or None),
                       "after": after_fn, "error": err_fn},
        }
    finally:
        _close_gd()


# --------------------------------------------------------------------------- #
# READ-ONLY discovery: scan GraphDef.Optionen properties, current values, and
# which selection-list tokens a property accepts (values restored afterwards).
# Use this to learn the real Fomode / Foname tokens instead of guessing.
# --------------------------------------------------------------------------- #
_OPT_PROP_CANDIDATES = [
    # layout mode / type
    "Fomode", "Foart", "Fotyp", "Fotype", "Fokind", "Foformat",
    # layout file name (the "Name" field + browse)
    "Foname", "Fofile", "Fopath", "Loname", "Lofile", "Layoutname", "Layoutfile",
    "Vorlage", "Vorlagename", "Formatname", "Formatfile", "Name",
    # working mode / misc
    "Modus", "Mode", "Type", "Art", "Kind",
]
_FOMODE_VALUE_CANDIDATES = [
    "None", "Fix", "Variable", "Variabel", "Fest", "Frei", "Free",
    "Normal", "Standard", "User", "Benutzer", "Layout",
    "0", "1", "2", "3",
]


@mcp.tool()
def scan_optionen(prop: str = "", try_values: str = "") -> dict:
    """READ-ONLY discovery of GraphDef.Optionen.

    With no args: read a broad set of candidate Optionen properties and report each
    one's current value (or that the property does not exist). Use this to see the
    real property names and current state (e.g. Fomode, Foname).

    With `prop` set: additionally probe candidate string values against that
    property and report which ones PAK accepts (i.e. are in its selection list),
    then restore the original value. This is how to discover the real token behind
    a UI label such as Layout = "Variable".

    Args:
        prop: Optionen property to value-probe (e.g. "Fomode").
        try_values: comma-separated candidate values to test. If empty and
            prop == "Fomode", a default candidate set is used.
    """
    out = {"ok": False, "current": {}, "probe": None}
    try:
        _open_gd(visible=True)
        _ev("set opt [$gd Optionen]")

        # 1) read current values of candidate properties
        for p in _OPT_PROP_CANDIDATES:
            try:
                out["current"][p] = _ev("$opt %s" % p)
            except Exception as exc:
                msg = str(exc).splitlines()[0]
                if "Unbekannte" in msg or "Unknown" in msg or "nknown" in msg:
                    continue  # property does not exist -> skip silently
                out["current"][p] = "<err:%s>" % msg[:60]

        # 2) value-probe a specific property (non-destructive: restore at end)
        if prop:
            cands = [c.strip() for c in try_values.split(",") if c.strip()]
            if not cands:
                cands = _FOMODE_VALUE_CANDIDATES if prop.lower() == "fomode" else []
            before = None
            try:
                before = _ev("$opt %s" % prop)
            except Exception as exc:
                before = "<err:%s>" % str(exc).splitlines()[0][:60]
            accepted, rejected = [], []
            for c in cands:
                try:
                    _ev("$opt %s %s" % (prop, _brace(c)))
                    after = _ev("$opt %s" % prop)
                    accepted.append({"tried": c, "stored_as": after})
                except Exception as exc:
                    rejected.append({"tried": c,
                                     "error": str(exc).splitlines()[0][:70]})
            # restore original
            restored = None
            if before is not None and not str(before).startswith("<err"):
                try:
                    _ev("$opt %s %s" % (prop, _brace(before)))
                    restored = _ev("$opt %s" % prop)
                except Exception as exc:
                    restored = "<restore-failed:%s>" % str(exc).splitlines()[0][:50]
            out["probe"] = {"prop": prop, "before": before,
                            "accepted": accepted, "rejected": rejected,
                            "restored": restored}

        _ev("catch {release $opt}; unset opt")
        out["ok"] = True
        return out
    finally:
        _close_gd()


# --------------------------------------------------------------------------- #
# GPS position tools.  GPS42 G2 module channels (latitude / longitude / speed /
# altitude) are recorded as SLOW quantities, exactly like CAN signals
# (Slow throughput -> Slow quantity, Srate Original, NO averaging).  Two views:
#   * configure_gps_track_row(s) -> geographic ROUTE: LATITUDE (Y) vs LONGITUDE
#     (X), built by putting the longitude channel on the Track (Par.-channel)
#     axis so the two slow channels plot against each other (a lat/lon track).
#   * configure_gps_row(s)       -> a GPS slow channel (speed / latitude / ...)
#     drawn vs TIME (default) or vs another slow channel such as vehicle SPEED.
# GPS channel quantity names come from PAK's Quantity catalogue and depend on the
# setup; pass the EXACT position/direction/quantity from PAK_Browser.get_channels
# (direction is usually 'S').  Latitude / Longitude / Speed are common quantity
# names but verify against the real GPS measurement's channel list.
# --------------------------------------------------------------------------- #
def _apply_gps_track_row(row, active=None, diagram=None, curve=None, measurement=None,
    lat_position=None, lat_direction="S", lat_quantity=None,
    lon_position=None, lon_direction="S", lon_quantity=None):
    """One row = geographic route.  Y axis = LATITUDE (Slow quantity); the
    LONGITUDE channel is put on the Track (Par.-channel) axis so it becomes the X
    axis -> a latitude-vs-longitude driving track.  No averaging; axes auto lin."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: LATITUDE as Slow quantity (Y axis) ---
    _ev("set dt [$it Datentyp]")
    _ev("$dt SetChanpos %s %s %s" % (_brace(lat_position),
        _brace(lat_direction if lat_direction is not None else "S"), _brace(lat_quantity)))
    _ev("$dt Mdtype %s" % _brace("Slow throughput"))
    _ev("$dt Srate %s" % _brace("Original"))
    _ev("$dt Pdtype %s" % _brace("Slow quantity"))
    steps["y_channel"] = {"position": lat_position,
                          "direction": lat_direction if lat_direction is not None else "S",
                          "quantity": lat_quantity}
    steps["measurement_data_type"] = "Slow throughput"
    steps["graphic_data_type"] = "Slow quantity"
    _ev("catch {release $dt}; unset dt")
    # --- Track parameter = LONGITUDE channel -> becomes the X axis ---
    _ev("set tp [$it TrackingParams]")
    _ev("$tp SetChanposTrack %s %s %s" % (_brace(lon_position),
        _brace(lon_direction if lon_direction is not None else "S"), _brace(lon_quantity)))
    _ev("$tp Start %s" % _brace("Min"))
    _ev("$tp Stop %s" % _brace("Max"))
    steps["x_channel"] = {"position": lon_position,
                          "direction": lon_direction if lon_direction is not None else "S",
                          "quantity": lon_quantity}
    _ev("catch {release $tp}; unset tp")
    # --- X (lon) + Y (lat) axes -> auto lin so the route fills the diagram ---
    _ev("set sd [$it SkalenDefinition]")
    _ev("set ax [$sd AchsenSkalierung]")
    _ev("$ax Aktiv1_ 1"); _ev("$ax Type1_ %s" % _brace("lin"))
    _ev("$ax Von1_ %s" % _brace("OFF")); _ev("$ax Bis1_ %s" % _brace("OFF"))
    _ev("$ax Aktiv2_ 1"); _ev("$ax Type2_ %s" % _brace("lin"))
    _ev("$ax Von2_ %s" % _brace("OFF")); _ev("$ax Bis2_ %s" % _brace("OFF"))
    steps["x_axis"] = "auto lin (longitude)"
    steps["y_axis"] = "auto lin (latitude)"
    _ev("catch {release $ax}; unset ax")
    _ev("catch {release $sd}; unset sd")
    _ev("catch {release $it}; unset it")
    return steps


def _apply_gps_signal_row(row, active=None, diagram=None, curve=None, measurement=None,
    position=None, direction="S", quantity=None,
    track_quantity="Time", track_position=None, track_direction="S",
    track_start=None, track_stop=None):
    """One row = a GPS slow channel (speed / latitude / longitude / altitude)
    drawn vs TIME (track_quantity='Time', default) or vs another slow channel such
    as vehicle SPEED (set track_quantity to that channel's quantity together with
    track_position / track_direction).  Slow quantity, no averaging, axes auto."""
    steps = {}
    idx = row - 1
    _ev("set it [$gd Item %d]" % idx)
    if active is not None:
        _ev("$it Active %d" % (1 if active else 0)); steps["active"] = bool(active)
    if diagram is not None:
        _ev("$it Diag %d" % int(diagram)); steps["diagram"] = int(diagram)
    if curve is not None:
        _ev("$it Curve %d" % int(curve)); steps["curve"] = int(curve)
    if measurement:
        measurement = _cp_suffix(measurement)
        _ev("$it Datafile %s" % _brace(measurement)); steps["measurement"] = measurement
    # --- Data type: Slow throughput -> Slow quantity ---
    _ev("set dt [$it Datentyp]")
    if quantity:
        _dir = direction if direction is not None else "S"
        _ev("$dt SetChanpos %s %s %s" % (_brace(position), _brace(_dir), _brace(quantity)))
        steps["channel"] = {"position": position, "direction": _dir, "quantity": quantity}
    _ev("$dt Mdtype %s" % _brace("Slow throughput"))
    _ev("$dt Srate %s" % _brace("Original"))
    _ev("$dt Pdtype %s" % _brace("Slow quantity"))
    steps["measurement_data_type"] = "Slow throughput"
    steps["graphic_data_type"] = "Slow quantity"
    _ev("catch {release $dt}; unset dt")
    # --- Track parameter: Time (default) or a slow channel (e.g. Speed) ---
    _ev("set tp [$it TrackingParams]")
    tq = track_quantity or "Time"
    if tq == "Time":
        _ev("$tp SetChanposTrack {} {} %s" % _brace("Time"))
        steps["track"] = {"quantity": "Time"}
    else:
        _tdir = track_direction if track_direction is not None else "S"
        _ev("$tp SetChanposTrack %s %s %s" % (_brace(track_position), _brace(_tdir), _brace(tq)))
        steps["track"] = {"position": track_position, "direction": _tdir, "quantity": tq}
    _ev("$tp Start %s" % _brace(track_start if track_start is not None else "Min"))
    _ev("$tp Stop %s" % _brace(track_stop if track_stop is not None else "Max"))
    _ev("catch {release $tp}; unset tp")
    # --- X + Y axes -> auto lin ---
    _ev("set sd [$it SkalenDefinition]")
    _ev("set ax [$sd AchsenSkalierung]")
    _ev("$ax Aktiv1_ 1"); _ev("$ax Type1_ %s" % _brace("lin"))
    _ev("$ax Von1_ %s" % _brace("OFF")); _ev("$ax Bis1_ %s" % _brace("OFF"))
    _ev("$ax Aktiv2_ 1"); _ev("$ax Type2_ %s" % _brace("lin"))
    _ev("$ax Von2_ %s" % _brace("OFF")); _ev("$ax Bis2_ %s" % _brace("OFF"))
    steps["x_axis"] = "auto lin (%s)" % tq
    steps["y_axis"] = "auto lin (value)"
    _ev("catch {release $ax}; unset ax")
    _ev("catch {release $sd}; unset sd")
    _ev("catch {release $it}; unset it")
    return steps


@mcp.tool()
def configure_gps_track_row(row: int, measurement: str = "",
    lat_position: str = "", lat_direction: str = "S", lat_quantity: str = "Latitude",
    lon_position: str = "", lon_direction: str = "S", lon_quantity: str = "Longitude",
    active: bool = True, diagram: int = 1, curve: int = 1, output: bool = False) -> dict:
    """Draw ONE GPS driving route (geographic track): LATITUDE (Y) vs LONGITUDE (X),
    then optionally run Graphic Output.

    The route is built by plotting the latitude channel as a Slow quantity and
    putting the longitude channel on the Track (Par.-channel) axis, so the two slow
    channels plot against each other -> the vehicle path. No averaging; axes auto lin.

    Args:
        measurement: subtitle, e.g. "ROAD_01/Run_01" (a " [CP]" tag is added).
        lat_position/lat_direction/lat_quantity: the LATITUDE channel (direction
            usually 'S'). quantity defaults to "Latitude" -- verify with
            PAK_Browser.get_channels for the real GPS measurement.
        lon_position/lon_direction/lon_quantity: the LONGITUDE channel. quantity
            defaults to "Longitude".
        diagram/curve: overlay several routes by giving each measurement its own
            curve in the SAME diagram (or use configure_gps_track_rows).
    """
    try:
        _open_gd()
        steps = _apply_gps_track_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None,
            lat_position=lat_position or None, lat_direction=lat_direction or "S",
            lat_quantity=lat_quantity or None,
            lon_position=lon_position or None, lon_direction=lon_direction or "S",
            lon_quantity=lon_quantity or None)
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_gps_track_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Overlay MANY GPS driving routes (LATITUDE vs LONGITUDE) in ONE COM session,
    then Graphic Output. Put every route in the SAME diagram, each measurement its
    own curve, to compare tracks. Non-RMS -> standard.vas_dly layout.

    Each row object: row plus any of active/diagram/curve/measurement/
    lat_position/lat_direction/lat_quantity/lon_position/lon_direction/lon_quantity.
    Example row:
      {"row":1,"diagram":1,"curve":1,"measurement":"ROAD_01/Run_01 [CP]",
       "lat_position":"GPS","lat_direction":"S","lat_quantity":"Latitude",
       "lon_position":"GPS","lon_direction":"S","lon_quantity":"Longitude"}
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement",
            "lat_position", "lat_direction", "lat_quantity",
            "lon_position", "lon_direction", "lon_quantity")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            steps = _apply_gps_track_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_gps_row(row: int, measurement: str = "", position: str = "",
    direction: str = "S", quantity: str = "", track_quantity: str = "Time",
    track_position: str = "", track_direction: str = "S",
    track_start: str = "Min", track_stop: str = "Max",
    active: bool = True, diagram: int = 1, curve: int = 1, output: bool = False) -> dict:
    """Plot ONE GPS slow channel (speed / latitude / longitude / altitude) vs TIME
    (default) or vs another slow channel such as vehicle SPEED, then optionally run
    Graphic Output.

    Fixed per row (like CAN): Slow throughput -> Slow quantity, Srate Original, NO
    averaging, X/Y axes auto so the real range shows.

    Args:
        position/direction/quantity: the GPS channel (direction usually 'S'),
            e.g. GPS / S / Speed.
        track_quantity: 'Time' (default) plots value vs time. To plot vs speed,
            set this to the speed channel's quantity (e.g. 'Speed') and give
            track_position/track_direction for that channel.
        diagram/curve: put each quantity in its own diagram; overlay runs as curves.
    """
    try:
        _open_gd()
        steps = _apply_gps_signal_row(row, active=active, diagram=diagram, curve=curve,
            measurement=measurement or None, position=position or None,
            direction=direction or "S", quantity=quantity or None,
            track_quantity=track_quantity or "Time",
            track_position=track_position or None, track_direction=track_direction or "S",
            track_start=track_start, track_stop=track_stop)
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
            steps["graphic_output"] = True
        return {"ok": True, "row": row, "applied": steps}
    finally:
        _close_gd()
        _reset()


@mcp.tool()
def configure_gps_rows(rows: str, deactivate_beyond: int = 0, output: bool = True) -> dict:
    """Plot MANY GPS slow channels (speed / latitude / longitude / altitude) in ONE
    COM session -- each vs TIME (default) or vs another slow channel such as vehicle
    SPEED -- then Graphic Output. Same slow-quantity mechanism as CAN (Slow
    throughput -> Slow quantity, Srate Original, NO averaging, axes auto).
    Non-RMS -> standard.vas_dly layout.

    Each row object: row plus any of active/diagram/curve/measurement/position/
    direction/quantity/track_quantity/track_position/track_direction/track_start/
    track_stop. track_quantity defaults to 'Time'.
    Example (speed vs time):
      {"row":1,"diagram":1,"curve":1,"measurement":"ROAD_01/Run_01 [CP]",
       "position":"GPS","direction":"S","quantity":"Speed"}
    Example (latitude vs speed):
      {"row":1,"diagram":1,"measurement":"ROAD_01/Run_01 [CP]",
       "position":"GPS","quantity":"Latitude",
       "track_quantity":"Speed","track_position":"GPS"}
    """
    data = json.loads(rows) if isinstance(rows, str) else rows
    keys = ("active", "diagram", "curve", "measurement", "position", "direction",
            "quantity", "track_quantity", "track_position", "track_direction",
            "track_start", "track_stop")
    try:
        _open_gd(visible=True)
        results = []
        listed = set()
        for r in data:
            rr = dict(r); rownum = int(rr.get("row")); listed.add(rownum)
            kw = {k: rr.get(k) for k in keys if k in rr}
            kw.setdefault("active", True)
            steps = _apply_gps_signal_row(rownum, **kw)
            results.append({"row": rownum, "applied": steps})
        if deactivate_beyond and int(deactivate_beyond) > 0:
            for rn in range(1, int(deactivate_beyond) + 1):
                if rn not in listed:
                    _ev("set it [$gd Item %d]" % (rn - 1))
                    _ev("$it Active 0")
                    _ev("catch {release $it}; unset it")
        if output:
            _apply_layout("standard.vas_dly", _STD_LAYOUT_TEMPLATE)
            _ev("$gd Graphicoutput")
        return {"ok": True, "rows": results,
                "deactivated_beyond": int(deactivate_beyond or 0), "output": bool(output)}
    finally:
        _close_gd()
        _reset()


# --------------------------------------------------------------------------- #
# Graphic Viewer toolbar UI automation. PAK's viewer toolbar actions (GPS map,
# cursor mode, scale, preset, playback ...) are Qt/C++ UI only -- NOT exposed as
# Tcl/COM commands (verified via pak_eval introspection). So they must be driven
# by clicking the toolbar buttons via UI Automation. Run viewer_lineup() first to
# re-align the toolbars to standard positions, then locate/click buttons.
# --------------------------------------------------------------------------- #
def _viewer_buttons(win):
    """List clickable toolbar-ish controls in the Graphic Viewer, left-to-right.
    Each: {name, autoid, ctype, rect:[l,t,r,b], _c:control}."""
    out = []

    def walk(c, d=0):
        for ch in c.GetChildren():
            try:
                ct = ch.ControlTypeName
                br = ch.BoundingRectangle
                aid = ""
                try:
                    aid = ch.AutomationId or ""
                except Exception:
                    pass
                if (ct in ("ButtonControl", "SplitButtonControl", "CheckBoxControl",
                           "ComboBoxControl", "RadioButtonControl")
                        and br.width() > 0 and br.height() > 0):
                    out.append({"name": (ch.Name or ""), "autoid": aid, "ctype": ct,
                                "rect": [br.left, br.top, br.right, br.bottom], "_c": ch})
            except Exception:
                pass
            if d < 12:
                walk(ch, d + 1)

    walk(win)
    out.sort(key=lambda b: (b["rect"][1] // 20, b["rect"][0]))  # row, then left
    return out


def _click_menuitem(auto, patterns, timeout=2.5):
    """After a right-click, find a MenuItem whose Name matches any regex in
    `patterns` (case-insensitive) among all popups and Invoke/click it."""
    import time, re
    rx = re.compile("|".join(patterns), re.I)
    hit = [None]

    def walk(c, d=0):
        for ch in c.GetChildren():
            try:
                if ch.ControlTypeName in ("MenuItemControl", "ListItemControl",
                                          "ButtonControl", "TextControl") and rx.search(ch.Name or ""):
                    if ch.ControlTypeName != "TextControl":
                        hit[0] = ch
                        return
            except Exception:
                pass
            if hit[0] is None and d < 8:
                walk(ch, d + 1)

    t0 = time.time()
    while time.time() - t0 < timeout:
        hit[0] = None
        for w in auto.GetRootControl().GetChildren():
            walk(w)
            if hit[0] is not None:
                break
        if hit[0] is not None:
            try:
                hit[0].GetInvokePattern().Invoke()
            except Exception:
                try:
                    hit[0].Click(simulateMove=False)
                except Exception:
                    return False
            return True
        time.sleep(0.2)
    return False


@mcp.tool()
def viewer_toolbar_dump(save_png: str = "C:/MCPproject_pak/viewer_toolbar.png") -> dict:
    """List the Graphic Viewer toolbar buttons (name/tooltip, AutomationId, type,
    rect), left-to-right, so specific controls (GPS/map button, cursor-mode, scale,
    preset, playback ...) can be identified. Optional screenshot to save_png.
    READ-ONLY (no clicks). Run viewer_lineup() first for stable positions."""
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err}
    win = _find_viewer_window(auto)
    if not win:
        return {"ok": False, "error": "Graphic Viewer window not found. Run a Graphic Output first."}
    btns = _viewer_buttons(win)
    res = [{k: b[k] for k in ("name", "autoid", "ctype", "rect")} for b in btns]
    out = {"ok": True, "count": len(res), "buttons": res}
    if save_png:
        ok, info = _capture_viewer(save_png)
        out["capture"] = info if ok else {"error": info}
    return out


@mcp.tool()
def viewer_lineup() -> dict:
    """Right-click the Graphic Viewer toolbar/menu area and click 'Line up' to
    re-align all toolbars to their standard positions. Do this BEFORE locating or
    clicking toolbar buttons so their positions are predictable. Requires uiautomation."""
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err}
    import time
    win = _find_viewer_window(auto)
    if not win:
        return {"ok": False, "error": "Graphic Viewer window not found. Run a Graphic Output first."}
    try:
        win.SetActive()
    except Exception:
        pass
    time.sleep(0.3)
    br = win.BoundingRectangle
    # Right-click on the menu-bar strip, just right of the '?' menu (an empty area
    # of the top band) to raise the toolbar context menu.
    mbar = None
    for c in win.GetChildren():
        try:
            if c.ControlTypeName == "MenuBarControl":
                mbar = c
                break
        except Exception:
            pass
    if mbar is not None:
        mb = mbar.BoundingRectangle
        px, py = mb.right + 40, (mb.top + mb.bottom) // 2
        if px > br.right - 5:
            px = mb.right + 10
    else:
        px, py = br.left + (br.right - br.left) // 2, br.top + 55
    auto.RightClick(px, py)
    time.sleep(0.5)
    ok = _click_menuitem(auto, [r"line\s*up", r"ausrichten", r"정렬"])
    time.sleep(0.4)
    if not ok:
        # dismiss any open menu
        try:
            auto.SendKeys("{Esc}")
        except Exception:
            pass
        return {"ok": False, "error": "'Line up' menu item not found after right-click.",
                "right_click_at": [px, py]}
    return {"ok": True, "message": "Toolbars lined up.", "right_click_at": [px, py]}


@mcp.tool()
def viewer_click(name: str = "", index: int = -1, right_click: bool = False,
                 menuitem: str = "", capture: bool = False) -> dict:
    """Click a Graphic Viewer toolbar button, identified by tooltip `name` (substring,
    case-insensitive) OR by 0-based left-to-right `index`. Use right_click=True +
    `menuitem` to open the button's context menu and click a menu item (substring).
    Set capture=True to screenshot the viewer afterwards. Requires uiautomation.

    Examples:
        viewer_click(name="GPS")                 # open GPS map (if tooltip has 'GPS')
        viewer_click(name="cursor", menuitem="double", right_click=True)
        viewer_click(index=42)                   # click the Nth toolbar button
    """
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err}
    import time, re
    win = _find_viewer_window(auto)
    if not win:
        return {"ok": False, "error": "Graphic Viewer window not found. Run a Graphic Output first."}
    btns = _viewer_buttons(win)
    target = None
    if name:
        rx = re.compile(re.escape(name), re.I)
        cands = [b for b in btns if rx.search(b["name"])]
        if not cands:
            return {"ok": False, "error": "no toolbar button matches name %r" % name,
                    "available": [b["name"] for b in btns if b["name"]][:60]}
        target = cands[0]
    elif index >= 0:
        if index >= len(btns):
            return {"ok": False, "error": "index %d out of range (0..%d)" % (index, len(btns) - 1)}
        target = btns[index]
    else:
        return {"ok": False, "error": "provide name or index"}
    try:
        win.SetActive()
    except Exception:
        pass
    time.sleep(0.2)
    c = target["_c"]
    try:
        if right_click:
            c.RightClick(simulateMove=False)      # context menu
        elif menuitem:
            c.Click(simulateMove=False)           # LEFT click opens a dropdown menu
        else:
            try:
                c.GetInvokePattern().Invoke()
            except Exception:
                c.Click(simulateMove=False)
        # If a menu item was requested, click it in the popup that just opened
        # (works for both right-click context menus and left-click dropdowns like
        # the Single/Double cursor selector).
        if menuitem:
            time.sleep(0.4)
            if not _click_menuitem(auto, [re.escape(menuitem)]):
                try:
                    auto.SendKeys("{Esc}")
                except Exception:
                    pass
                return {"ok": False, "error": "menu item %r not found" % menuitem,
                        "clicked_button": target["name"]}
    except Exception as e:
        return {"ok": False, "error": "click failed: %s" % str(e).splitlines()[0][:200]}
    time.sleep(0.5)
    out = {"ok": True, "clicked": {"name": target["name"], "ctype": target["ctype"],
           "rect": target["rect"]}, "right_click": bool(right_click), "menuitem": menuitem}
    if capture:
        ok, info = _capture_viewer("C:/MCPproject_pak/view_shot.png")
        out["capture"] = info if ok else {"error": info}
    return out


# --------------------------------------------------------------------------- #
# GPS same-location matching. A segment is picked (via the map + cursors) on a
# REFERENCE run; to compare the SAME road location on other-speed runs, map the
# segment's lat/lon endpoints to each run's own time window (different speed ->
# different times). Reads BusData NMEA + theader starttime straight from disk.
# Works regardless of whether the later analysis uses a time or a distance axis,
# and needs no Distance channel.
# --------------------------------------------------------------------------- #
def _meas_folder(dest, measurement):
    m = (measurement or "").strip()
    if m.endswith("]"):
        m = m.rsplit("[", 1)[0].strip()      # drop trailing " [CP]"
    parts = [p for p in m.replace("\\", "/").split("/") if p]
    return os.path.join(dest.replace("\\", "/"), *parts)


def _hav_m(la1, lo1, la2, lo2):
    import math
    R = 6371000.0
    r = math.pi / 180.0
    h = (math.sin((la2 - la1) * r / 2) ** 2
         + math.cos(la1 * r) * math.cos(la2 * r) * math.sin((lo2 - lo1) * r / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def _gps_points(folder):
    """Return [[t_meas, lat, lon, kmh], ...] and the raw starttime string for a
    measurement folder, from theader.xml (starttime) + PAK_Throughput0/mea_BusData*
    ($GPRMC NMEA). t_meas = fix UTC - starttime (t=0 at the trigger)."""
    import re, glob
    from datetime import datetime, timezone
    th = os.path.join(folder, "theader.xml")
    with open(th, encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    m = re.search(r"<starttime>([^<]*)</starttime>", txt)
    if not m:
        raise RuntimeError("no <starttime> in %s" % th)
    st = m.group(1)
    dt0 = datetime.strptime(st[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    st_s = dt0.timestamp() + (int(st[14:]) / 10 ** len(st[14:]) if st[14:] else 0.0)
    datebase = st[:8]
    bus = sorted(glob.glob(os.path.join(folder, "PAK_Throughput0", "mea_BusData*")))
    if not bus:
        raise RuntimeError("no PAK_Throughput0/mea_BusData* in %s" % folder)
    raw = open(bus[0], "rb").read().decode("latin-1")

    def latf(v, h):
        d = int(v[:2]); mm = float(v[2:]); x = d + mm / 60.0
        return -x if h in ("S", "s") else x

    def lonf(v, h):
        d = int(v[:3]); mm = float(v[3:]); x = d + mm / 60.0
        return -x if h in ("W", "w") else x

    pts = []
    for line in re.findall(r"\$GPRMC[^*]*\*[0-9A-Fa-f]{2}", raw):
        f = line.split(",")
        if len(f) < 10 or f[2] != "A":
            continue
        try:
            sec = f[1].split(".")
            dt = datetime.strptime(datebase + sec[0].zfill(6), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            futc = dt.timestamp() + (float("0." + sec[1]) if len(sec) > 1 else 0.0)
            pts.append([round(futc - st_s, 3), latf(f[3], f[4]), lonf(f[5], f[6]),
                        round(float(f[7]) * 1.852, 2) if f[7] else 0.0])
        except Exception:
            continue
    if not pts:
        raise RuntimeError("no valid $GPRMC fixes in %s" % bus[0])
    return pts, st


@mcp.tool()
def gps_match_segment(ref_measurement: str, t1: float, t2: float,
                      target_measurements: str) -> dict:
    """Map a GPS segment picked on a REFERENCE run to the SAME geographic location in
    other runs (different speed -> different time window). Feed the result straight
    into output_rms / configure_*_rows (track_start/track_stop) for same-location
    comparison across speeds. Needs no Distance channel; works for time- or
    distance-axis analysis.

    How: reads each measurement's BusData NMEA ($GPRMC) + theader `starttime` from disk
    to build (measurement-time, lat, lon). Gets the reference segment's endpoints A(t1)
    /B(t2) lat/lon, then for each target finds the times whose lat/lon are nearest A
    and B (reports the match distance in metres so you can sanity-check).

    Args:
        ref_measurement: measurement the segment was picked on, e.g. "GPSDATA/100_GPS".
        t1, t2: segment start/end seconds (t=0 at trigger; from read_viewer_cursors).
        target_measurements: JSON list, e.g. '["GPSDATA/80_GPS","GPSDATA/120_GPS"]'.

    Returns: ref A/B (t,lat,lon) and per-target {track_start, track_stop, match_m:{A,B}}.
    A match_m of a few metres = same location (GPS/fix resolution); tens of metres or
    more means the target may not cover that spot — check before trusting it.
    """
    import json as _json
    try:
        _ensure_sourced()
        _ev("set reference [createobject $pak_application]")
        try:
            _ev("set browser [$reference Browser]")
            dest = _ev("$browser DestDataPath")
        finally:
            _ev("catch {release $browser}; unset browser")
            _ev("catch {release $reference}; unset reference")
        targets = _json.loads(target_measurements) if isinstance(target_measurements, str) else target_measurements
        rp, rst = _gps_points(_meas_folder(dest, ref_measurement))

        def at(pts, tt):
            return min(pts, key=lambda p: abs(p[0] - tt))

        A = at(rp, float(t1)); B = at(rp, float(t2))
        out = {"ok": True, "data_path": dest,
               "ref": {"measurement": ref_measurement,
                       "A": {"t": A[0], "lat": round(A[1], 6), "lon": round(A[2], 6)},
                       "B": {"t": B[0], "lat": round(B[1], 6), "lon": round(B[2], 6)}},
               "targets": []}
        for tg in targets:
            try:
                tp, _ = _gps_points(_meas_folder(dest, tg))
                pa = min(tp, key=lambda p: _hav_m(p[1], p[2], A[1], A[2]))
                pb = min(tp, key=lambda p: _hav_m(p[1], p[2], B[1], B[2]))
                da = _hav_m(pa[1], pa[2], A[1], A[2]); db = _hav_m(pb[1], pb[2], B[1], B[2])
                lo, hi = sorted([pa[0], pb[0]])
                out["targets"].append({
                    "measurement": tg,
                    "track_start": round(lo, 3), "track_stop": round(hi, 3),
                    "match_m": {"A": round(da, 1), "B": round(db, 1)},
                    "A_t": pa[0], "B_t": pb[0]})
            except Exception as e:
                out["targets"].append({"measurement": tg, "error": str(e).splitlines()[0][:200]})
        return out
    except Exception as e:
        return {"ok": False, "error": str(e).splitlines()[0][:300]}


@mcp.tool()
def open_gps_map(capture: bool = False) -> dict:
    """Open the PAK GPS Map Viewer by clicking the 'Open map' button (the GPS icon at
    the right end of the Graphic Viewer toolbar). Run a Graphic Output first so the
    Graphic Viewer is open. The map is time + coordinate synced with the data: select
    a segment on it, then call read_viewer_cursors() to get t1/t2 for windowed
    analysis (e.g. output_rms track_start/track_stop). Uses exact-name matching on the
    button (avoids the 'single/double cursor' substring collision). Requires uiautomation."""
    auto, err = _import_uiautomation()
    if auto is None:
        return {"ok": False, "error": "uiautomation import failed: %s" % err}
    import time
    win = _find_viewer_window(auto)
    if not win:
        return {"ok": False, "error": "Graphic Viewer window not found. Run a Graphic Output first."}
    target = None
    for b in _viewer_buttons(win):
        if (b["name"] or "").strip().lower() == "open map":
            target = b
            break
    if target is None:
        return {"ok": False, "error": "'Open map' button not found (try viewer_lineup first)."}
    try:
        win.SetActive()
    except Exception:
        pass
    time.sleep(0.2)
    try:
        target["_c"].GetInvokePattern().Invoke()
    except Exception:
        target["_c"].Click(simulateMove=False)
    time.sleep(0.4)
    out = {"ok": True, "message": "Clicked 'Open map' -- GPS Map Viewer opened.",
           "button_rect": target["rect"]}
    if capture:
        ok, info = _capture_viewer("C:/MCPproject_pak/view_shot.png")
        out["capture"] = info if ok else {"error": info}
    return out


@mcp.tool()
def pak_eval(script: str, in_pak: bool = True) -> dict:
    """DEBUG / introspection: evaluate an arbitrary Tcl `script`.

    The PAK COM object exposes essentially one method -- EvalTclScript -- so ALL PAK
    automation is Tcl. This tool sends `script` to be evaluated INSIDE the running PAK
    interpreter (in_pak=True, via `$reference EvalTclScript`) and returns the result
    string; set in_pak=False to run it in the local client interpreter instead.

    Use it to discover PAK's internal commands, e.g.:
        script="info commands *ap*"      # map / playback ...
        script="info commands *eom*"     # geom / geometry
        script="info procs *arte*"       # Karte (German = map)
        script="info commands *iew*"     # view / viewer
    then, if a map-opening command is found, call it directly (no UI click).
    """
    try:
        _ensure_sourced()
        if in_pak:
            _ev("set reference [createobject $pak_application]")
            try:
                res = _ev("$reference EvalTclScript %s" % _brace(script))
            finally:
                _ev("catch {release $reference}; unset reference")
        else:
            res = _ev(script)
        return {"ok": True, "in_pak": bool(in_pak), "script": script, "result": res}
    except Exception as e:
        return {"ok": False, "in_pak": bool(in_pak), "script": script,
                "error": str(e).splitlines()[0][:300]}


if __name__ == "__main__":
    mcp.run()
