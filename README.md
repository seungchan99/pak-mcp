# PAK Graphic Definition MCP server

Automates the Mueller-BBM **PAK** *Graphic Definition* window and runs **Graphic
Output**, exposed as MCP tools. It drives PAK through PAK's official **Tcl COM
bridge** (`tkinter.Tcl()` + `createobject`/`release`), the same mechanism the
other PAK MCP servers use. This is required because PAK's grid-row objects fault
under raw `win32com`; they need PAK's own reference protocol.

## Confirmed working on this machine

Everything below was validated live against PAK 6.4:

- Row (grid): Active, Diagr., Curve, Name of Measurement
- Data type: channel position/direction/quantity (`SetChanpos`), Measurement
  data type (`Mdtype`, e.g. Throughput), Graphic data type (`Pdtype`, e.g. APS),
  sampling rate (`Srate`)
- Track parameter: `SetChanposTrack {} {} Time`, range from `Min` to `Max`
- Graphic Output: `GraphDef.Graphicoutput`

Key facts discovered: COM ProgID is `Pak.Application.1`; the grid row index is
**0-based** (`Item 0` == row 1); every handle must be released in reverse order.

## Tools

- `pak_open_graphdef` — open/show the Graphic Definition window
- `set_row(row, active, diagram, curve, measurement)`
- `set_data_type(row, position, direction, quantity, measurement_data_type, graphic_data_type, sampling_rate)`
- `set_track(row, track_quantity, start, stop)`
- `set_weighting(row, weighting)` — A / B / C / lin
- `graphic_output()`
- `configure_row(...)` — full row in one call, `output=True` to render
- `release_all()` — force-release handles if PAK gets locked

Rows are **1-based** in the tools (converted to PAK's 0-based `Item` internally).

## Frequency weighting note

The Display/Filter "Freq. weighting" field maps to a PAK data-type property. The
two confirmed properties that accept A/B/C/lin are `Tp2det_fweight` and
`Tp2oct_fweight`; `set_weighting` tries them in order (`PAK_WEIGHT_PROPS`).
Verify visually which one moves the Display/Filter field for your analysis type,
then pin it via the env var if needed.

## Requirements

- Windows with PAK 6.4 installed.
- Python 3.10+ with `tkinter` (bundled with standard Python on Windows).
- `pip install -r requirements.txt` (installs `mcp`).

## Configuration (environment variables)

- `PAK_TCL_INIT` — path to PAK's Tcl init file. Default
  `C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl`.
- `PAK_WEIGHT_PROPS` — weighting property names to try, in order. Default
  `Tp2det_fweight,Tp2oct_fweight`.

## claude_desktop_config.json

```json
{
  "mcpServers": {
    "PAK": {
      "command": "python",
      "args": ["C:\\MCPProject_pak\\pak_graphdef_mcp.py"]
    }
  }
}
```

Restart Claude Desktop after editing the config so the PAK server reloads.

## Example (matches the screenshots)

```
pak_open_graphdef
configure_row(
  row=1, active=true, diagram=1, curve=1,
  measurement="ExampleMOI/Acceleration_Run_01 [CP]",
  position="Gear Lever", direction="+X", quantity="Acceleration",
  measurement_data_type="Throughput", graphic_data_type="APS", sampling_rate="32768",
  track_quantity="Time", track_start="Min", track_stop="Max",
  weighting="A", output=true
)
```

## Track "Stat. parameter" (2D reduction) — via COM `Stats`

The Track parameter **Stat. parameter** IS settable over COM: property `Stats`
on `TrackingParams`, with PAK's exact internal tokens. Use the `stat_parameter`
option on `configure_row` / `configure_rows` (friendly name auto-mapped):

| stat_parameter (friendly) | PAK token (`$tp Stats {...}`) |
|---|---|
| `-` / `3D` (no reduction, 3D waterfall) | `-` |
| `Average [lin]` | `Mittelwert   [lin]` |
| `Average [Q]`   | `Mittelwert   [  Q]` |
| `Maximum`       | `Maximum` |
| `Minimum`       | `Minimum` |
| `dB Average [lin]` | `Mittelwert dB [lin]` |
| `dB Average [Q]`   | `Mittelwert dB [  Q]` |
| Std.dev / dB variants | see `STAT_MAP` in the server |

Setting a stat value reduces the time axis -> **2D spectrum** (overlayable);
setting `-` restores the **3D** waterfall. This is pure COM/Tcl — no UI needed.

Example — Diagram 1 = rows 1-3 Maximum, Diagram 2 = rows 4-6 Average, one call:

```
configure_rows(rows='[
 {"row":1,"diagram":1,"curve":1,"measurement":"ExampleMOI/Acceleration_Run_01 [CP]","position":"Gear Lever","direction":"+X","quantity":"Acceleration","measurement_data_type":"Throughput","graphic_data_type":"APS","sampling_rate":"32768","stat_parameter":"Maximum"},
 {"row":2,"diagram":1,"curve":2,"measurement":"ExampleMOI/Acceleration_Run_02 [CP]","position":"Gear Lever","direction":"+X","quantity":"Acceleration","measurement_data_type":"Throughput","graphic_data_type":"APS","sampling_rate":"32768","stat_parameter":"Maximum"},
 {"row":3,"diagram":1,"curve":3,"measurement":"ExampleMOI/Acceleration_Run_03 [CP]","position":"Gear Lever","direction":"+X","quantity":"Acceleration","measurement_data_type":"Throughput","graphic_data_type":"APS","sampling_rate":"32768","stat_parameter":"Maximum"},
 {"row":4,"diagram":2,"curve":1,"measurement":"ExampleMOI/Acceleration_Run_01 [CP]","position":"Gear Lever","direction":"+X","quantity":"Acceleration","measurement_data_type":"Throughput","graphic_data_type":"APS","sampling_rate":"32768","stat_parameter":"Average [Q]"},
 {"row":5,"diagram":2,"curve":2,"measurement":"ExampleMOI/Acceleration_Run_02 [CP]","position":"Gear Lever","direction":"+X","quantity":"Acceleration","measurement_data_type":"Throughput","graphic_data_type":"APS","sampling_rate":"32768","stat_parameter":"Average [Q]"},
 {"row":6,"diagram":2,"curve":3,"measurement":"ExampleMOI/Acceleration_Run_03 [CP]","position":"Gear Lever","direction":"+X","quantity":"Acceleration","measurement_data_type":"Throughput","graphic_data_type":"APS","sampling_rate":"32768","stat_parameter":"Average [Q]"}
]', output=true)
```

## GPS position tools (GPS42 G2 module)

GPS channels (latitude / longitude / speed / altitude) are recorded as **Slow
quantities**, like CAN. Pass the exact channel `position`/`direction`/`quantity`
from `PAK_Browser.get_channels` (direction usually `S`); the default quantity
names below ("Latitude"/"Longitude"/"Speed") are placeholders.

- `configure_gps_track_row` / `configure_gps_track_rows` — geographic **route**:
  latitude (Y) vs longitude (X). Built by putting the longitude channel on the
  Track (Par.-channel) axis so the two slow channels plot against each other.
  Overlay several measurements as curves in one diagram to compare routes.
- `configure_gps_row` / `configure_gps_rows` — a GPS slow channel (speed /
  latitude / longitude / altitude) vs **Time** (default) or vs another slow
  channel such as **Speed** (set `track_quantity` + `track_position`). Same
  slow-quantity mechanism as CAN: Slow throughput → Slow quantity, Srate
  Original, no averaging, axes auto. Non-RMS → `standard.vas_dly` layout.

```
configure_gps_track_rows(rows='[
 {"row":1,"diagram":1,"curve":1,"measurement":"ROAD_01/Run_01 [CP]",
  "lat_position":"GPS","lat_direction":"S","lat_quantity":"Latitude",
  "lon_position":"GPS","lon_direction":"S","lon_quantity":"Longitude"}
]', output=true)

configure_gps_rows(rows='[
 {"row":1,"diagram":1,"curve":1,"measurement":"ROAD_01/Run_01 [CP]",
  "position":"GPS","direction":"S","quantity":"Speed"}
]', output=true)
```

> No GPS channels exist in the sample "전기모터" bench project — verify against a
> loaded GPS road-test measurement. If a channel is not recognized, follow the
> "recommend Auto, ask don't auto-fix" rule.
