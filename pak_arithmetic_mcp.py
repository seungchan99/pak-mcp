# -*- coding: utf-8 -*-
"""PAK Arithmetic MCP server (Tcl COM bridge).

Generates PAK Arithmetic formulas (APS_ANLY today, extensible) with automatic
signature selection + validation, and injects them into PAK's Arithmetic window.

Like pak_graphdef_mcp.py, this drives PAK through its official Tcl COM bridge
(createobject / release reference protocol) rather than raw win32com, because
PAK's nested objects (AriVariables rows, Datatype) require that protocol.

Config (environment variables):
    PAK_TCL_INIT   Path to PAK's Tcl init file. Default:
                   C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl

Tools:
    list_functions()          - registered arithmetic functions
    describe_function(name)    - parameter schema + rules
    build_formula(...)         - validated APS_ANLY call text (no PAK needed)
    build_formula_document(...)- full "SET_PARAM + RESULT=..." document text
    pak_probe_arithmetic(...)  - READ-ONLY: discover how to reach the Arithmetic
                                 object and which members exist (run first!)
"""
import os
import tkinter as tk

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("PAK_Arithmetic")

PAK_TCL_INIT = os.environ.get(
    "PAK_TCL_INIT",
    "C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl",
)

# --------------------------------------------------------------------------- #
# Low-level Tcl helpers (mirrors pak_graphdef_mcp.py)
# --------------------------------------------------------------------------- #
_tcl = tk.Tcl()
_sourced = False


def _ev(cmd):
    return _tcl.eval(cmd)


def _brace(value):
    """Quote a value for Tcl as a single {..} token."""
    s = "" if value is None else str(value)
    return "{%s}" % s


def _ensure_sourced():
    global _sourced
    if not _sourced:
        _ev("source {%s}" % PAK_TCL_INIT)
        _sourced = True
    _ev("set pak_application")  # confirm the application id is defined


def _reset():
    """Release any lingering COM handles from a previous (aborted) call."""
    for v in ["dt", "row", "av", "ari", "it", "gd", "reference"]:
        try:
            _ev("if {[info exists %s]} { catch {release $%s}; unset %s }" % (v, v, v))
        except Exception:
            pass


def _release(*names):
    for v in names:
        try:
            _ev("catch {release $%s}; unset %s" % (v, v))
        except Exception:
            pass


# =========================================================================== #
# Formula generation (validated, no PAK required)
# =========================================================================== #
WIN_TYPES = ["RECT", "HANN", "FLATTOP"]
AVG_TYPES = ["AVG_NONE", "AVG_LIN_NUM", "AVG_EXP_NUM", "AVG_MAX_NUM", "AVG_MIN_NUM"]
TRACK_TYPES = ["slow_quantity", "tacho_edges", "slow_throughput"]

SIG_SLOW_QUANTITY = "TRACK=slow_quantity (steps from TRACK)"
SIG_TIME = "time tracking (no TRACK)"
SIG_RANGE = "TRACK=tacho_edges/slow_throughput (explicit range)"


class ValidationError(ValueError):
    pass


def _flag(value, allowed, name):
    if value is None:
        raise ValidationError("%s is required" % name)
    text = str(value).strip().upper()
    for a in allowed:
        if text == a.upper():
            return a
    raise ValidationError("%s=%r invalid. Allowed: %s" % (name, value, ", ".join(allowed)))


def _pos_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("%s must be an integer, got %r" % (name, value))
    if value <= 0:
        raise ValidationError("%s must be positive, got %s" % (name, value))
    return value


def _check_n_avg(value, avg_type):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("n_avg must be an integer, got %r" % value)
    if value < 0:
        raise ValidationError("n_avg must be >= 0, got %s" % value)
    if avg_type != "AVG_NONE" and value < 1:
        raise ValidationError("n_avg must be >= 1 unless avg_type is AVG_NONE, got %s" % value)
    return value


def _is_symbolic(v):
    return isinstance(v, str) and v.strip().upper() in ("MIN", "MAX")


def _rank(v):
    if isinstance(v, str):
        u = v.strip().upper()
        if u == "MIN":
            return float("-inf")
        if u == "MAX":
            return float("inf")
        raise ValidationError("Unknown symbolic boundary: %r" % v)
    return float(v)


def _fmt_boundary(v):
    if isinstance(v, str):
        u = v.strip().upper()
        if u in ("MIN", "MAX"):
            return u
        raise ValidationError("Unknown symbolic boundary: %r" % v)
    return _fmt_num(v)


def _fmt_num(v):
    if isinstance(v, bool):
        raise ValidationError("numeric value must not be bool")
    if isinstance(v, int):
        return str(v)
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def _norm_boundary(v):
    return v.strip().upper() if _is_symbolic(v) else float(v)


def build_aps_anly(params):
    """Validate params, pick signature, return {formula, signature, normalized}."""
    p = dict(params)
    arg = p.get("arg")
    if not arg or not str(arg).strip():
        raise ValidationError("arg (ARG variable name) is required")
    arg = str(arg).strip()

    block_size = _pos_int(p.get("block_size"), "block_size")
    win_type = _flag(p.get("win_type"), WIN_TYPES, "win_type")
    avg_type = _flag(p.get("avg_type"), AVG_TYPES, "avg_type")
    n_avg = _check_n_avg(p.get("n_avg"), avg_type)

    overlap = p.get("overlap")
    if overlap is None or isinstance(overlap, bool) or not isinstance(overlap, (int, float)):
        raise ValidationError("overlap must be a number in [0,1], got %r" % overlap)
    if not (0.0 <= float(overlap) <= 1.0):
        raise ValidationError("overlap must be within [0,1], got %s" % overlap)

    track = p.get("track")
    track = str(track).strip() if track not in (None, "") else None
    track_type_raw = p.get("track_type")
    trackstart = p.get("trackstart")
    trackdelta = p.get("trackdelta")
    trackstop = p.get("trackstop")

    head = [arg, _fmt_num(block_size), win_type, avg_type, _fmt_num(n_avg),
            _fmt_num(float(overlap))]
    normalized = {"arg": arg, "block_size": block_size, "win_type": win_type,
                  "avg_type": avg_type, "n_avg": n_avg, "overlap": float(overlap)}

    if track is None:
        if track_type_raw is not None:
            raise ValidationError("track_type given but no track dataset provided")
        if trackstart is None or trackdelta is None:
            raise ValidationError("time tracking (no TRACK) requires trackstart and trackdelta")
        _check_delta(trackdelta)
        tail = [_fmt_boundary(trackstart), _fmt_num(float(trackdelta))]
        normalized.update(trackstart=_norm_boundary(trackstart), trackdelta=float(trackdelta))
        if trackstop is not None:
            _check_order(trackstart, trackstop)
            tail.append(_fmt_boundary(trackstop))
            normalized["trackstop"] = _norm_boundary(trackstop)
        else:
            normalized["trackstop"] = "MAX (implicit)"
        signature = SIG_TIME
    else:
        track_type = _flag(track_type_raw, TRACK_TYPES, "track_type")
        normalized.update(track=track, track_type=track_type)
        if track_type == "slow_quantity":
            for nm, val in (("trackstart", trackstart), ("trackdelta", trackdelta),
                            ("trackstop", trackstop)):
                if val is not None:
                    raise ValidationError(
                        "track_type=slow_quantity defines steps by TRACK alone; "
                        "%s must not be given" % nm)
            tail = [track]
            signature = SIG_SLOW_QUANTITY
        else:
            missing = [nm for nm, val in (("trackstart", trackstart),
                                          ("trackdelta", trackdelta),
                                          ("trackstop", trackstop)) if val is None]
            if missing:
                raise ValidationError(
                    "tacho_edges/slow_throughput tracking requires %s" % ", ".join(missing))
            _check_delta(trackdelta)
            _check_order(trackstart, trackstop)
            tail = [track, _fmt_boundary(trackstart), _fmt_num(float(trackdelta)),
                    _fmt_boundary(trackstop)]
            normalized.update(trackstart=_norm_boundary(trackstart),
                              trackdelta=float(trackdelta),
                              trackstop=_norm_boundary(trackstop))
            signature = SIG_RANGE

    formula = "APS_ANLY(" + ", ".join(head + tail) + ")"
    return {"formula": formula, "signature": signature, "normalized_params": normalized}


def _check_delta(trackdelta):
    if isinstance(trackdelta, bool) or not isinstance(trackdelta, (int, float)):
        raise ValidationError("trackdelta must be a number, got %r" % trackdelta)
    if float(trackdelta) <= 0:
        raise ValidationError("trackdelta must be positive, got %s" % trackdelta)


def _check_order(trackstart, trackstop):
    if _rank(trackstart) >= _rank(trackstop):
        raise ValidationError("trackstart (%s) must occur earlier than trackstop (%s)"
                              % (trackstart, trackstop))


# --------------------------------------------------------------------------- #
# Extensible function registry: add an entry to support a new PAK function.
# --------------------------------------------------------------------------- #
FUNCTIONS = {
    "APS_ANLY": {
        "summary": "Auto Power Spectrum (APS) of a throughput dataset ARG. "
                   "Auto-selects one of three signatures from TRACK presence/type.",
        "builder": build_aps_anly,
        "parameters": [
            ("arg", "string", True, "Variable name of the throughput dataset (ARG)."),
            ("block_size", "int", True, "Block size for the spectral transform."),
            ("win_type", "enum", True, "Window function: " + ", ".join(WIN_TYPES)),
            ("avg_type", "enum", True, "Averaging type: " + ", ".join(AVG_TYPES)),
            ("n_avg", "int", True, "Number of averages (0 only with AVG_NONE)."),
            ("overlap", "float", True, "Block overlap, 0..1."),
            ("track", "string", False, "Variable name of tracking dataset (TRACK)."),
            ("track_type", "enum", False, "Type of TRACK: " + ", ".join(TRACK_TYPES)),
            ("trackstart", "number|MIN|MAX", False, "Start of tracking range."),
            ("trackdelta", "float", False, "Distance between track values (>0)."),
            ("trackstop", "number|MIN|MAX", False, "End of tracking range."),
        ],
    },
}


def _get_fn(name):
    key = (name or "").upper()
    if key not in FUNCTIONS:
        raise ValidationError("Unknown function %r. Known: %s"
                              % (name, ", ".join(sorted(FUNCTIONS))))
    return FUNCTIONS[key]


def _build(name, params):
    return _get_fn(name)["builder"](params)


# --------------------------------------------------------------------------- #
# Formula-document assembly (SET_PARAM declarations + RESULT = ...)
# --------------------------------------------------------------------------- #
_STRING_FLAGS = {"DATA_TYPE"}


def _render_set_param(target, source, flag, value):
    if flag.upper() in _STRING_FLAGS or isinstance(value, str):
        val = "'%s'" % value
    else:
        val = str(value)
    return "%s = SET_PARAM(%s, %s, %s)" % (target, source, flag, val)


# =========================================================================== #
# MCP tools
# =========================================================================== #
@mcp.tool()
def list_functions() -> dict:
    """List registered PAK Arithmetic functions and their parameters."""
    out = []
    for name, spec in FUNCTIONS.items():
        out.append({
            "name": name,
            "summary": spec["summary"],
            "parameters": [
                {"name": n, "type": t, "required": r, "description": d}
                for (n, t, r, d) in spec["parameters"]
            ],
        })
    return {"functions": out}


@mcp.tool()
def describe_function(name: str) -> dict:
    """Return the parameter schema and rules for one arithmetic function."""
    try:
        spec = _get_fn(name)
    except ValidationError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "name": name.upper(),
        "summary": spec["summary"],
        "parameters": [
            {"name": n, "type": t, "required": r, "description": d}
            for (n, t, r, d) in spec["parameters"]
        ],
    }


@mcp.tool()
def build_formula(
    name: str = "APS_ANLY",
    arg: str = "",
    block_size: int = 0,
    win_type: str = "",
    avg_type: str = "",
    n_avg: int = 0,
    overlap: float = 0.0,
    track: str = None,
    track_type: str = None,
    trackstart=None,
    trackdelta: float = None,
    trackstop=None,
) -> dict:
    """Build a validated PAK Arithmetic call, auto-selecting the signature.

    trackstart/trackstop accept numbers or the symbols "MIN"/"MAX".
    Returns {ok, formula, signature, normalized_params} or {ok: false, error}.
    """
    params = dict(arg=arg, block_size=block_size, win_type=win_type,
                  avg_type=avg_type, n_avg=n_avg, overlap=overlap, track=track,
                  track_type=track_type, trackstart=trackstart,
                  trackdelta=trackdelta, trackstop=trackstop)
    try:
        r = _build(name, params)
    except ValidationError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **r}


@mcp.tool()
def build_formula_document(
    name: str = "APS_ANLY",
    arg: str = "",
    block_size: int = 0,
    win_type: str = "",
    avg_type: str = "",
    n_avg: int = 0,
    overlap: float = 0.0,
    result_name: str = "RESULT",
    declarations: list = None,
    track: str = None,
    track_type: str = None,
    trackstart=None,
    trackdelta: float = None,
    trackstop=None,
) -> dict:
    """Build the full Arithmetic-Window text (SET_PARAM declarations + RESULT=...).

    ``declarations`` = list of {"target","source","flag"?,"value"?}, e.g.
        [{"target":"acc1","source":"ac1","flag":"DATA_TYPE","value":"Throughput"}]
    yields:  acc1 = SET_PARAM(ac1, DATA_TYPE, 'Throughput')
    then appends:  <result_name> = APS_ANLY(arg, ...)
    """
    params = dict(arg=arg, block_size=block_size, win_type=win_type,
                  avg_type=avg_type, n_avg=n_avg, overlap=overlap, track=track,
                  track_type=track_type, trackstart=trackstart,
                  trackdelta=trackdelta, trackstop=trackstop)
    try:
        r = _build(name, params)
    except ValidationError as exc:
        return {"ok": False, "error": str(exc)}

    lines = []
    for d in (declarations or []):
        lines.append(_render_set_param(
            d["target"], d["source"], d.get("flag", "DATA_TYPE"),
            d.get("value", "Throughput")))
    lines.append("%s = %s" % (result_name, r["formula"]))

    return {"ok": True, "document": "\n".join(lines),
            "formula": r["formula"], "signature": r["signature"],
            "result_name": result_name,
            "normalized_params": r["normalized_params"]}


@mcp.tool()
def pak_probe_arithmetic(row: int = 1) -> dict:
    """READ-ONLY discovery of the PAK Arithmetic object path and its members.

    Run this FIRST (with PAK open). It does not modify anything. It tries to
    reach an Arithmetic object via candidate paths and reads documented members
    so we can confirm the exact API before wiring full injection.

    ``row`` is the 1-based GraphDef grid row (COM Item is 0-based internally).
    """
    report = {"ok": False, "progid_env": os.environ.get("PAK_PROGID"),
              "tcl_init": PAK_TCL_INIT, "steps": [], "paths": [], "members": {}}
    try:
        _ensure_sourced()
        report["steps"].append("sourced init.tcl + $pak_application OK")
    except Exception as exc:
        report["steps"].append("source/init FAILED: %s" % exc)
        report["hint"] = ("Check PAK_TCL_INIT path and that PAK is installed. "
                          "Current: %s" % PAK_TCL_INIT)
        return report

    _reset()
    try:
        _ev("set reference [createobject $pak_application]")
        report["steps"].append("createobject reference OK")
    except Exception as exc:
        report["steps"].append("createobject FAILED: %s" % exc)
        _reset()
        return report

    # Candidate paths to reach an Arithmetic object.
    idx = int(row) - 1
    candidates = [
        ("reference.Arithmetic", "set ari [$reference Arithmetic]"),
        ("GraphDef.Item(%d).Arithmetic" % idx,
         "set gd [$reference GraphDef]; set it [$gd Item %d]; set ari [$it Arithmetic]" % idx),
    ]

    reached = False
    for label, cmd in candidates:
        entry = {"path": label, "reached": False, "error": None}
        try:
            for part in cmd.split("; "):
                _ev(part)
            entry["reached"] = True
            reached = True
        except Exception as exc:
            entry["error"] = str(exc)
        report["paths"].append(entry)
        if reached:
            report["arithmetic_path"] = label
            break
        _release("it", "gd", "ari")

    if not reached:
        report["steps"].append("could not reach any Arithmetic object")
        report["hint"] = ("Open the Arithmetic window in PAK, then retry. If it "
                          "lives elsewhere, paste this report and we'll map the path.")
        _reset()
        return report

    # Read-only member probe on the reached Arithmetic object ($ari).
    for prop in ["Mainpakvar", "Mainpakfor", "Mainmeasurement",
                 "Mainpara", "Mainparb", "Mainparc", "Mainpard",
                 "Mainpare", "Mainparf", "Mainparg", "Mainparh"]:
        try:
            val = _ev("$ari %s" % prop)
            report["members"][prop] = {"exists": True, "value": val}
        except Exception as exc:
            report["members"][prop] = {"exists": False, "error": str(exc)}

    # AriVariables collection.
    av = {"reached": False}
    try:
        _ev("set av [$ari AriVariables]")
        av["reached"] = True
        try:
            av["count"] = _ev("$av Count")
        except Exception as exc:
            av["count_error"] = str(exc)
        # Peek at first row if any.
        try:
            _ev("set row [$av Item 0]")
            av["item0_varname"] = _ev("$row Varname")
            try:
                _ev("set dt [$row Datatype]")
                av["item0_mdtype"] = _ev("$dt Mdtype")
                _release("dt")
            except Exception as exc:
                av["item0_datatype_error"] = str(exc)
            _release("row")
        except Exception as exc:
            av["item0_error"] = str(exc)
    except Exception as exc:
        av["error"] = str(exc)
    report["ari_variables"] = av
    _release("av")

    _reset()
    report["ok"] = True
    report["steps"].append("probe complete (read-only)")
    return report


@mcp.tool()
def pak_probe_scan(max_rows: int = 40, max_hits: int = 3) -> dict:
    """READ-ONLY: scan GraphDef rows to find existing Arithmetic definitions and
    learn how the formula text is stored.

    For each row it reads Arithmetic.Mainpakfor/Mainpakvar; for the first rows
    that are non-empty it also tries candidate formula-text accessors and dumps
    the populated AriVariables rows. Nothing is modified.
    """
    report = {"ok": False, "scanned": 0, "hits": [], "steps": []}
    # Candidate read-only accessors that might expose the formula TEXT.
    text_candidates = ["Formula", "Formeltext", "Text", "PakFor", "Formel",
                       "FormulaText", "Content"]
    try:
        _ensure_sourced()
        _reset()
        _ev("set reference [createobject $pak_application]")
        _ev("set gd [$reference GraphDef]")
        report["steps"].append("connected + GraphDef OK")
    except Exception as exc:
        report["steps"].append("connect FAILED: %s" % exc)
        _reset()
        return report

    hits = 0
    for i in range(int(max_rows)):
        try:
            _ev("set it [$gd Item %d]" % i)
            _ev("set ari [$it Arithmetic]")
        except Exception:
            _release("ari", "it")
            continue
        report["scanned"] += 1
        try:
            pakfor = _ev("$ari Mainpakfor")
            pakvar = _ev("$ari Mainpakvar")
        except Exception:
            pakfor = pakvar = ""
        if (pakfor or pakvar) and hits < int(max_hits):
            hits += 1
            hit = {"row": i + 1, "item_index": i, "Mainpakfor": pakfor,
                   "Mainpakvar": pakvar, "text_accessors": {}, "variables": []}
            for cand in text_candidates:
                try:
                    v = _ev("$ari %s" % cand)
                    hit["text_accessors"][cand] = {"exists": True,
                                                   "value_preview": (v or "")[:400]}
                except Exception:
                    hit["text_accessors"][cand] = {"exists": False}
            # dump populated AriVariables rows
            try:
                _ev("set av [$ari AriVariables]")
                cnt = int(_ev("$av Count"))
                for j in range(min(cnt, 20)):
                    try:
                        _ev("set row [$av Item %d]" % j)
                        vn = _ev("$row Varname")
                    except Exception:
                        _release("row")
                        continue
                    if vn:
                        vrow = {"index": j, "Varname": vn}
                        try:
                            vrow["Datafile"] = _ev("$row Datafile")
                        except Exception:
                            pass
                        try:
                            _ev("set dt [$row Datatype]")
                            try:
                                vrow["Mdtype"] = _ev("$dt Mdtype")
                            except Exception:
                                pass
                            _release("dt")
                        except Exception:
                            pass
                        hit["variables"].append(vrow)
                    _release("row")
                _release("av")
            except Exception as exc:
                hit["variables_error"] = str(exc)
            report["hits"].append(hit)
        _release("ari", "it")
        if hits >= int(max_hits):
            break

    _reset()
    report["ok"] = True
    report["steps"].append("scan complete (read-only)")
    return report


if __name__ == "__main__":
    mcp.run()
