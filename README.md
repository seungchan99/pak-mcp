# PAK MCP

MCP (Model Context Protocol) servers that let an LLM assistant drive **Müller-BBM
PAK** for NVH analysis — building Graphic Definitions, running Graphic Output,
and reading projects/measurements/channels.

They drive PAK through PAK's official **Tcl COM bridge**  <!-- servers included: PAK, PAK_Browser -->
(`tkinter.Tcl()` + `createobject`/`release`), the same mechanism PAK's own
scripting uses. This is required because PAK's grid-row objects fault under raw
`win32com`; they need PAK's own reference protocol.

> **About PAK.** PAK is a product of Müller-BBM VAS. This project automates a
> locally installed PAK and does not redistribute any PAK/Müller-BBM files.
> The source code is open (MIT) and free to use and modify — see
> [Trademarks](#trademarks) for how the PAK name and official releases are handled.

## Servers

| Server | File | What it does |
|---|---|---|
| `PAK` | `pak_graphdef_mcp.py` | Graphic Definition automation + Graphic Output; band-pass RMS tables (`output_rms`); APS/Octave/Overall/Order analyses; CAN/GPS tools |
| `PAK_Browser` | `pak_browser_mcp.py` | Read current project, measurements, and channel lists (no COM popups) |

> A third server, `PAK_Arithmetic` (arithmetic formulas), is under development and
> not included in this release yet.

> PAK allows only **one** COM connection at a time, so the servers run their
> calls sequentially, not in parallel.

## Requirements

- Windows with **PAK 6.4** installed.
- **Python 3.10+** with `tkinter` (bundled with standard Python on Windows).
- An MCP-capable client (e.g. Claude Desktop).

## Install

```powershell
git clone https://github.com/seungchan99/pak-mcp.git
cd pak-mcp
pip install -r requirements.txt
```

## Configuration

Copy `config.example.json` into your client's MCP config (for Claude Desktop:
`%APPDATA%\Claude\claude_desktop_config.json`), then edit the three `args`
paths to point at where you cloned the servers. Restart the client so the
servers reload.

```jsonc
{
  "mcpServers": {
    "PAK":         { "command": "python", "args": ["C:\\path\\to\\pak_graphdef_mcp.py"], "env": { "PAK_PROGID": "Pak.Application.1" } },
    "PAK_Browser": { "command": "python", "args": ["C:\\path\\to\\pak_browser_mcp.py"],  "env": { "PAK_PROGID": "Pak.Application.1" } }
  }
}
```

### Environment variables

- `PAK_PROGID` — PAK COM ProgID. Default `Pak.Application.1`.
- `PAK_TCL_INIT` — path to PAK's Tcl init file. Default
  `C:/Program Files/MuellerBBM-VAS/PAK 6.4/tcl/pak_library/clnt/init.tcl`.
- `PAK_WEIGHT_PROPS` — weighting property names to try, in order. Default
  `Tp2det_fweight,Tp2oct_fweight`.

## Confirmed working (PAK 6.4)

Validated live against PAK 6.4:

- Row (grid): Active, Diagr., Curve, Name of Measurement
- Data type: channel position/direction/quantity (`SetChanpos`), Measurement
  data type (`Mdtype`, e.g. Throughput), Graphic data type (`Pdtype`, e.g. APS),
  sampling rate (`Srate`)
- Track parameter: `SetChanposTrack {} {} Time`, range from `Min` to `Max`
- Graphic Output: `GraphDef.Graphicoutput`

Key facts: COM ProgID is `Pak.Application.1`; the grid row index is **0-based**
(`Item 0` == row 1); every handle must be released in reverse order.

## Tools (PAK / graphdef)

`pak_open_graphdef`, `set_row`, `set_data_type`, `set_track`, `set_weighting`
(A/B/C/lin), `graphic_output`, `configure_row` / `configure_rows`,
`output_rms`, and analysis helpers (`configure_octave_rows`,
`configure_overall_rows`, `configure_orderaps_rows`,
`configure_ordercomplex_rows`, CAN/GPS variants), plus `release_all` to
force-release handles if PAK gets locked. Rows are **1-based** in the tools
(converted to PAK's 0-based `Item` internally).

### Example

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

## Frequency weighting note

The Display/Filter "Freq. weighting" field maps to a PAK data-type property. The
two confirmed properties that accept A/B/C/lin are `Tp2det_fweight` and
`Tp2oct_fweight`; `set_weighting` tries them in order (`PAK_WEIGHT_PROPS`).
Verify visually which one moves the Display/Filter field for your analysis type.

## Track "Stat. parameter" (2D reduction) — via COM `Stats`

The Track "Stat. parameter" is settable over COM (`Stats` on `TrackingParams`).
Use the `stat_parameter` option on `configure_row` / `configure_rows` (friendly
name auto-mapped):

| stat_parameter (friendly) | PAK token |
|---|---|
| `-` / `3D` (no reduction) | `-` |
| `Average [lin]` | `Mittelwert   [lin]` |
| `Average [Q]`   | `Mittelwert   [  Q]` |
| `Maximum`       | `Maximum` |
| `Minimum`       | `Minimum` |
| `dB Average [lin]` | `Mittelwert dB [lin]` |
| `dB Average [Q]`   | `Mittelwert dB [  Q]` |

Setting a stat value reduces the time axis → **2D spectrum** (overlayable);
setting `-` restores the **3D** waterfall.

## GPS position tools (GPS42 G2)

GPS channels (latitude / longitude / speed / altitude) are recorded as **Slow
quantities**, like CAN. Pass the exact channel `position`/`direction`/`quantity`
from `PAK_Browser.get_channels` (direction usually `S`).

- `configure_gps_track_row` / `configure_gps_track_rows` — geographic route
  (latitude Y vs longitude X).
- `configure_gps_row` / `configure_gps_rows` — a GPS slow channel vs Time
  (default) or vs another slow channel such as Speed.

## Skill

`skills/pak-nvh/SKILL.md` is a companion skill describing how to drive these
tools (RMS recipes, comparison plots, sound-vs-vibration reporting rules).

## Trademarks

The **source code** in this repository is open source under the MIT license — you
are free to use, modify, and redistribute it, including commercially.

However, **"PAK", "PAK MCP", and the Müller-BBM name and logos are trademarks** of
Müller-BBM VAS and are **not** covered by the MIT license. You may not use these
names or logos to brand, name, or distribute a modified/derivative version in a way
that suggests it is an official or endorsed release.

**Official releases** are published by Müller-BBM VAS / PAK System Co., Ltd. If you
distribute a modified version, please give it a different name and make clear it is
not affiliated with or endorsed by Müller-BBM.

## License

Source code: [MIT](LICENSE) © 2026 PAK System Co., Ltd.
Trademarks: see [Trademarks](#trademarks) above (not licensed under MIT).
