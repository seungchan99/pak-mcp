---
name: "pak-nvh"
description: "Drive the PAK NVH MCP tools (PAK, PAK_Browser, PAK_Arithmetic) to build Graphic Definitions, output band-pass RMS tables, and build 2D comparison plots (overlaying several measurements/channels as APS/Octave curves). Use whenever the user asks to compute or output RMS, band-pass RMS, RMS 값/표, compare/비교 measurements, load PAK measurements/channels, set up APS/Octave/Order/Detector analyses, run exterior/pass-by/tire/정속 (constant-speed) noise (외부소음) analyses, choose the Track parameter Par.-channel (Time vs Distance), or run PAK Graphic Output. IMPORTANT: in PAK, 'RMS 분석' means band-pass RMS (Sum level 1 = Bandpaß mag) drawn as a TABLE on the graph via the RMS.vas_dly LAYOUT and read back from a screenshot — it is NOT a separate arithmetic/analysis. Always drive it through the output_rms tool, never by hand-configuring rows. For exterior/pass-by noise decide the Track Par.-channel FAST: Distance (Cart. Coord.x / Distance, range -10..20) for 정속/pass-by/tire runs, else Time."
---

# PAK NVH automation

These MCP servers are always available in every Claude Desktop window:

- **PAK** — Graphic Definition automation + `output_rms` (band-pass RMS table) + `ensure_rms_layout` + `set_layout_mode` + `reset_graphdef`.
- **PAK_Browser** — read the current project, measurements, and channel lists.
- **PAK_Arithmetic** — build arithmetic formulas (separate feature; not RMS).

PAK allows only **one** COM connection at a time, so run tools sequentially, not in parallel.

## 외부소음 / Exterior (pass-by) noise — Track parameter Par.-channel (DECIDE FAST)

This is the #1 thing to get right quickly for exterior work. When the task is
**exterior / pass-by / 정속(constant-speed) / tire (타이어) noise** — cues like
`외부소음`, `정속평가`, `pass-by`, `TireA_18in`, `50kph`, a mic array the vehicle
drives past — the analysis **types are the same as interior** (3D APS, 2D APS,
1/3-Octave) **plus Detector**. The ONE thing that differs is the **Track parameter
Par.-channel**, and it is a fixed decision — do NOT probe or deliberate, just pick:

| Task type | Track Par.-channel | Range for track |
|---|---|---|
| Exterior pass-by / 정속 / tire (DEFAULT) | **Distance** — `Distance S ; Cart. Coord.x / Distance` (position `Distance`, direction `S`, quantity `Cart. coord.x`) | **from -10 to 20** (m) |
| Time trace / no distance channel | **Time** | Min .. Max (default) |

**KEY FACT — the Distance track needs a POSITION label; quantity alone FAILS.**
A channel track (Distance) cannot be set with an empty position: PAK rejects
`SetChanposTrack {} {} {Cart. coord.x}` with
`0x80040200 Working mode ... requires a position label`. So you MUST give the track its
position/direction, not just the quantity. (Time is fine without a position — Time is
not a channel.)

**Recipe (server ≥ track_position support — the normal path):**
`configure_row` / `configure_rows` / `set_track` now take **`track_position`** and
**`track_direction`**. Set the whole exterior row — channel + Detector/APS/Octave +
A-weighting + Distance track — in ONE `configure_rows` call, no `pak_eval`:

```json
{"row":1,"diagram":1,"curve":1,"measurement":"정속평가/01_TireA_18in_18in_가을_50kph_1",
 "position":"Left Side","direction":"S","quantity":"Sound Pressure",
 "measurement_data_type":"Throughput","graphic_data_type":"Detector","sampling_rate":"32768",
 "weighting":"A",
 "track_position":"Distance","track_direction":"S","track_quantity":"Cart. coord.x",
 "track_start":"-10","track_stop":"20"}
```

Use the EXACT position/direction/quantity `get_channels` reports (Position `Distance`,
Direction `S`, Quantity **`Cart. coord.x`** — lowercase `coord`; the dialog title-cases
it to `Cart. Coord.x` but the COM token is the lowercase one). For a Time track just omit
`track_position` and pass `track_quantity="Time"`. Then `capture_viewer` + Read the PNG to
confirm X = metres -10..20, Y = dB(A).

> **Fallback (older server without `track_position`):** configure the rows WITHOUT any
> track fields (`configure_rows(..., output=false)` — sets channel+Detector+A), then set
> the Distance track with the position label via `pak_eval(in_pak=false)` looping items:
> `set reference [createobject $pak_application]; set gd [$reference GraphDef]; $gd Visible 1;`
> for each item `set tp [$it TrackingParams]; $tp SetChanposTrack {Distance} {S} {Cart. coord.x}; $tp Start {-10}; $tp Stop {20}`
> then `$gd Graphicoutput` and release handles. Only needed if the tools reject
> `track_position`.

Everything else (Average mode `Default`, A-weighting for sound, 32768/16384, the
`Average [Q]` 2D reduction for overlays, RMS via `output_rms`) is unchanged from the
interior recipes below.

## Analysis & reporting: ALWAYS separate Sound vs Vibration

When interpreting or summarizing any result (Order APS, Order complex, APS/RMS
comparisons, etc.), **keep Sound (Sound Pressure, 소음) and Vibration (Acceleration,
진동) in SEPARATE groups** — they are different physical quantities (Pa vs m/s²),
different units/scales, and different transfer paths, so a mixed ranking is misleading.

- Report each group on its own (per-order / per-RPM behaviour, dominant channel/axis),
  then add a short **cross-group correlation** (e.g. "vibration is high at orders 5/8
  but only order 2 radiates into sound").
- Prefer laying them out separately on the graph too (sound channels in one diagram,
  vibration channels in another) rather than overlaying Pa and m/s² in one diagram.
- Countermeasure priority follows the sound path: an order that is strong in vibration
  but weak in sound is a structural/durability item, not an interior-noise item.

## What "RMS" means here (read this first)

When the user says "RMS 분석해줘", "RMS 값 출력", "band-pass RMS", they mean:

> Compute the **band-pass RMS** (Sum level 1 = `Bandpaß mag`) over a frequency band for each channel, draw the values as a **table on the graph** using the **RMS.vas_dly layout**, run Graphic Output, then read the numbers from a screenshot.

This is done **entirely by the `output_rms` tool**. Do **not** interpret it as PAK_Arithmetic, cursor readout, or Export. Do not hand-build rows with the granular `set_*`/`configure_*` tools for RMS — `output_rms` already applies APS, sampling 32768 / blocksize 16384, `Average [Q]`, the band, the layout, AND the band-pass Sum level, all in one call.

## Fully automatic — no manual setup, reset-safe

`output_rms` is self-contained. From a completely fresh or **reset** Graphic Definition it will, with **no UI step**:

1. Enable the layout: set `Optionen.Format = "Autoformat"` (this is what makes the
   layout file writable), then set `Optionen.Foname = "RMS.vas_dly"`.
2. Auto-create `RMS.vas_dly` in `<Tablepath>\AutoFormat` if it is missing.
3. Configure each row as an APS spectrum over the band, apply `Average [Q]`, and
   then set **Sum level 1 = band-pass magnitude** directly.

So you never need to pre-set the "Layout" dropdown or the "Sum level" field by hand.
If you just reset with `reset_graphdef`, the very next `output_rms` still produces
the full table with values.

### Sound is ALWAYS A-weighted

Noise/sound analysis is **always** done **A-weighted**, so **every** analysis tool
**auto-applies A-weighting to every Sound Pressure channel** — `output_rms`, `configure_rows`
/ `configure_row` (plain/3D APS, Octave), `configure_orderaps_rows`,
`configure_ordercomplex_rows`, `configure_octave_rows`, `configure_overall_rows`, and
`configure_detector_rows`. You do not need to ask or set it — sound rows come out **dB(A)**
by default; vibration (Acceleration) and other quantities stay **linear**.

> **Effective path per analysis family.** For APS-type spectra (plain/3D APS, **Order APS**,
> **Order complex**, band-pass RMS, Overall) the weighting MUST be set via
> **`Item.DarstFilter.Fweight = "A"`** (the Display/Filter → Freq. weighting field). This is
> the ONLY writable + effective path for these: `Datentyp.Tp2det_fweight` is writable but a
> **no-op** for them (verified: A vs lin gave identical 84.0), and `GesPegel.N1fbew` is
> **read-only**. With `DarstFilter.Fweight = A` the axis becomes dB(A) and the level drops
> correctly (e.g. 84.0 → 62.3). `DarstFilter` is an Item sub-object, so release Datentyp /
> GesPegel / TrackingParams before opening it. Octave uses `Tp2oct_fweight` and Detector uses
> `Tp2det_fweight` (both writable + effective for those types). The server helper
> `_emit_sound_fweight()` picks the right path automatically for every tool.

- Override per row: pass `weighting="A"|"B"|"C"|"lin"` (forces that weighting on the row).
- Disable the sound auto-rule for a row: `sound_weighting=""` (or `weighting="lin"`).
- Every `configure_*` / `output_rms` response echoes each row's applied `weighting`, so
  confirm sound rows say `A`.

> **History / gotcha.** Earlier server builds only auto-weighted RMS / Octave / Overall /
> Detector, while **Order APS, Order complex, and plain APS left sound linear** (and
> `configure_row(weighting="A")` silently went through the no-op `Tp2det_fweight`). This is
> **fixed** — those tools now apply `DarstFilter.Fweight`, so sound is A-weighted everywhere.
> Do NOT rely on `set_weighting(row,"A")` for an APS/Order row (it only tries the no-op
> `Tp2*_fweight`). If you ever hit an OLD server that still shows an Order APS sound channel
> as `dB(lin)`, weight it manually via `pak_eval(in_pak=false)`: for each item
> `set df [$it DarstFilter]; $df Fweight {A}` then `$gd Graphicoutput`.

## Fast RMS recipe (do it in this order)

1. **Find the data — always look it up, never assume names.** Every project uses
   different measurement/channel names; only the **format** is constant. The names
   in this file (`ExampleMOI/...`, `Gear Lever`, `+X`) are illustrative examples —
   do NOT reuse them. Get the real names each time:
   - `PAK_Browser.get_current_project` → confirm project/job.
   - `PAK_Browser.list_project_data` / `list_last_measurements` → measurement names (format: `Job/Name [CP]`).
   - `PAK_Browser.get_channels` → positions, directions (±X/±Y/±Z), quantities (Acceleration, Sound Pressure, …).

2. **Build the `rows` JSON** — one object per curve. Group curves into diagrams:
   ```json
   [{"row":1,"diagram":1,"curve":1,"measurement":"ExampleMOI/Acceleration_Run_01 [CP]",
     "position":"Gear Lever","direction":"+X","quantity":"Acceleration"}, ...]
   ```
   Put each channel/axis in its own `diagram` and each repeat/run in its own `curve`
   (so runs overlay per diagram = 2D comparison + one RMS value each).

3. **Call `output_rms` once**:
   - `rows` = the JSON above.
   - `band_from` / `band_to` = the RMS band in Hz. **The band = the displayed X-axis range** — `output_rms` sets it automatically.
   - `deactivate_beyond` = highest row number that might have leftovers (e.g. 12) to clear old rows.
   - `capture` = true → screenshot saved to `C:/MCPProject_pak/rms_shot.png`.
   - `draw_table` = true (default) draws the RMS value table. **Set `draw_table=false`
     to output the 2D comparison curves only, with NO RMS table** (the tool sets
     `Optionen.Format="Auto"`, i.e. the toolbar "Layout None"; the band-pass Sum level
     is skipped). Same rows, table on/off — handy for a curves-only comparison view.

> **Note:** the RMS numbers are drawn on the graph only; they are NOT returned in the
> tool's JSON response. To read the values you must `capture=true` and read the
> screenshot. With `capture=false` there are no fresh numbers to report.

4. **Read the result**: open `C:/MCPProject_pak/rms_shot.png` with the Read tool and
   report the RMS table values (Test / pos / RMS) back to the user, grouped by diagram.
   Confirm success by checking the response `sumlevel_token` is `BandpaÞ mag` (NOT `-`).
   - **If Read fails with "outside connected folders"** (i.e. `C:/MCPProject_pak` is
     not a mounted folder), first call `request_cowork_directory(path="C:/MCPProject_pak")`
     to mount it, then Read the PNG. This is the usual reason the screenshot "can't be
     opened" — it's a mount/path issue, not a capture failure.

That's the whole flow — usually two tool calls (browser lookup + `output_rms`) plus reading the image.

## Comparison output (여러 데이터 2D 오버레이 비교)

Use this when the user says "데이터 비교", "비교 출력", "APS/옥타브로 비교", or wants
several measurements/channels drawn as **overlaid 2D curves** in one graph (without the
RMS table). This is a normal Graphic Definition.

> **Shortcut:** if you already have (or want) the same channel/run layout as an RMS
> run, just call `output_rms(..., draw_table=false)` — it produces exactly these
> overlaid 2D curves with no RMS table, in one call. Use the manual `configure_row`
> recipe below only when you need finer control than `output_rms` offers.

### Layout convention

- **One diagram per channel/position**; **one curve per measurement/run** inside it,
  so the runs overlay for direct comparison. Fill diagram 1's curves first (rows 1..N),
  then diagram 2, etc.

### The 3D→2D gotcha (it WILL bite you)

APS/Octave over **Throughput** data is **3D** (time × frequency). Two 3D reps cannot
share one diagram, so `graphic_output` fails with:

> `0x80040200 Two 3D representations within one diagram not allowed !Graphicoutput failed`

Collapse each curve to 2D with a statistical reduction: `stat_parameter = "Average [Q]"`
(token `Mittelwert   [  Q]`). `output_rms` applies this automatically; for comparison
plots set it on each `configure_row`.

### Recipe

1. Look up real names (`get_current_project` → `list_project_data` → `get_channels`).
2. Grid: diagrams = channels to compare, curves = measurements to overlay.
3. For each row call `configure_row` with `diagram`, `curve`, `measurement`, `position`,
   `direction`, `quantity`, `measurement_data_type="Throughput"`,
   `graphic_data_type="APS"` (or `"Octave"`), `sampling_rate="32768"`,
   `stat_parameter="Average [Q]"`, `output=false`.
4. On the **last** row set `output=true` to render once.
5. Optional per row: `x_from`/`x_to` (band), `weighting="A"` (dB(A)), `y_type` (dB).

`configure_rows` (bulk) has no `stat_parameter`, so for overlays use `configure_row`
per row. Batch the per-row calls in a single turn to cut round trips (PAK serializes on
its one COM connection).

## How the automation works (for troubleshooting)

Two facts, both handled inside `output_rms` — only relevant if it ever fails:

- **Layout:** `Optionen.Foname` (the layout file) is read-only UNLESS `Optionen.Format`
  is `"Autoformat"`. The toolbar "Layout" None/Fix/Variable dropdown is UI-only and is
  NOT exposed via COM (`Format` always reads `Auto`/`Autoformat`; `Fomode` only accepts
  `Normal`). So the tool sets `Format="Autoformat"` first, then `Foname`.
  Use `set_layout_mode(mode="Autoformat", layout="RMS.vas_dly")` to do this manually.
- **Sum level token:** the special character is **U+00DE** (reads back as `BandpaÞ mag`),
  NOT the sz-ligature U+00DF. And it only appears in `GesPegel.N1gesp`'s selection list
  AFTER the row is an APS spectrum with a band-pass range. So the tool configures APS
  first, then sets `N1gesp` to the U+00DE token (built Tcl-side via `Þ` so Python
  never touches the raw byte). If `sumlevel_token` comes back `-`, the row was not APS
  when the sum level was set.
- **AutoFormat vs PlotEditor:** `AutoFormat` = RMS value-table layouts. `PlotEditor` =
  analysis definitions. Never mix them. **Never use Chancalctype.**
- **Saving:** only save the Graphic Definition when the user explicitly asks.

## Table font size

More diagrams → smaller diagrams → the RMS table may need to shrink. Change **only** the
table font (맑은 고딕):

- `ensure_rms_layout(table_fontsize=7, force=true)` → table cells + header to 7 pt
  (default original = 9/8). Then rerun `output_rms` to redraw.

## Exterior noise (외부소음 / pass-by / 정속) workflow

Main analysis methods: **3D APS, 2D APS, Octave 1/3, Detector** — the same methods as
interior work; only **Detector** is added for exterior (see the tools below).

**Track parameter (Par.-Channel) — Distance and Speed are freely switchable.** Easiest:
`configure_detector_rows` takes **`track_preset`** = `"distance"` (default) / `"speed"` /
`"time"` — one key picks the whole track (channel + quantity + range + delta). Explicit
`track_*` args still override. The presets are:
1. **Time** — only when the user explicitly asks (`track_quantity=""`; Delta in seconds).
2. **Distance** (DEFAULT for exterior/정속·pass-by):
   `track_position="Distance"`, `track_direction="S"`, `track_quantity="Cart. coord.x"`
   (lowercase 'coord'!), `track_start="-10"`, `track_stop="20"`, `delta="0.25"` (m).
   `configure_detector_rows` already defaults to exactly this.
3. **Speed** (가속 분석 / acceleration run): use **Distance by default; Speed only on
   request.** Speed preset:
   `track_position="Speed"`, `track_direction="S"`, `track_quantity="Driving Speed"`,
   `track_start="40"`, `track_stop="60"`, `delta="0.25"` (km/h). e.g. Vbox GPS speed.
   (RPM/Torque tracks work the same way via `track_quantity`.)

**Standard analysis order:**
1. **Detector** — compare **LH vs RH side** sound levels (left/right mic, distance track).
2. **3D APS** — judge the overall frequency-vs-distance/RPM noise picture.
3. **Band RMS** (`output_rms`) — a specific frequency band and compare.
4. **External influencing factors** (e.g. tire near-field noise comparison) — only on request.

Keep sound and vibration separate (see the separation rule above). All exterior sound is
A-weighted (auto for Sound Pressure channels).

## Other analyses (not RMS)

- Standard APS spectra (single curve per diagram): `configure_rows` (auto 32768 /
  blocksize 16384; **sound auto A-weighted via `Item.DarstFilter.Fweight`**; supports
  x_from/x_to, y_type, per-row `weighting=`). No `stat_parameter` — for overlays use
  `configure_row` (see Comparison output).
- **Octave / 1/3 octave** (소음 표준 스펙트럼): **`configure_octave_rows`**. Pdtype "Octave",
  `fraction` = the only real variable ("1/1","1/3"(default),"1/6","1/12","1/24"), Srate
  "Original", **Average [Q] required (2D)**, sound auto A-weighted (`Tp2oct_fweight`).
- **Overall / OA (전체레벨 vs 시간)**: **`configure_overall_rows`**, blocksize 16384. The
  Overall PlotDtype token is **build-dependent** — current builds expose it as **`"Overall"`**
  (older ones as **`"Sum level"`**), and only ONE is in the filtered selection list (setting the
  wrong one → `0x80040200 Value '…' not available in selection list 'PlotDtype'`). The tool now
  **tries `"Overall"` then `"Sum level"`** and keeps whichever the build accepts — so OA works
  directly from a fresh/reset definition, **no APS-context workaround needed**. Track = **Time**
  (Delta in seconds) OR a **value channel** (RPM/Speed/Torque via `track_quantity` +
  `track_position`). **Delta is in the track's units** — the tool guards RPM tracks against a
  leftover time-step (0.125 on an RPM track = 0.125-RPM steps → PAK hang); value-track with no
  delta → 30. Sound auto A-weighted. (For 레벨 vs 거리/속도 use `configure_detector_rows`.)
- **Detector** (레벨 detector; 외부소음/정속·패스바이 주 용도): **`configure_detector_rows`**.
  Pdtype "Detector", `detector_type` "rms", weighting `Tp2det_fweight` (writable + effective
  for Detector, unlike APS/RMS). **Default track = Distance** pass-by:
  `SetChanposTrack {Distance} {S} {Cart. coord.x}`, Start −10, Stop 20 m, Delta 0.25.
    - The distance quantity is **`Cart. coord.x`** (lowercase 'coord'); `Cart. Coord.x`
      returns "Error Quantity". The tool tries candidates and **verifies via `Trackquantity`
      read-back** (rejects "error"/"time"), so the axis really becomes Distance (m).
    - Switch track freely: Time = `track_quantity=""`; **Speed (가속) = `track_position="Speed"`,
      `track_quantity="Driving Speed"`, start 40 / stop 60 / delta 0.25**; RPM =
      `track_quantity="Rotational Speed"`. Detector type = rms, Time const = Fast/.125 s are
      PAK defaults (usually no need to set).
- Order analysis (차수): **sound channels are auto A-weighted** (via `Item.DarstFilter.Fweight`;
  vibration stays linear). Override per row with `weighting=`/`sound_weighting=`.
    - **Order APS** (order-frequency colormap): `configure_orderaps_rows` (Pdtype "Order APS",
      RPM track, `x_from`/`x_to` for the displayed order range).
    - **Order complex** (특정 차수 magnitude vs RPM): `configure_ordercomplex_rows` (order number,
      RPM track, X-axis always reset to auto).
    - **Maximum order** = the WRITABLE property **`Datentyp.Tp2spec_maxorder`** (the Data-type tab
      "Maximum order" field). Do NOT use `Item.Order.Ordto` for max order — it is **read-only** in
      this graphic definition and raises `Value can only be read`. Order Lines / Order Resol. are
      derived from blocksize + max order (do not set them). Blocksize = `Tp2spec_blocksize`.
- Reset: `reset_graphdef` (Ctrl+N). Pages: `list_pages` / `new_page` / `goto_page` / `delete_page`.
- Save/open: `save_graphdef` / `open_graphdef_file` / `list_graphdefs`.
- Working mode: `get_working_mode` / `set_working_mode`.

## 같은 GPS 위치 · 다속도 비교 (gps_match_segment)

주행 속도가 다른 여러 측정(예: 80/100/120 km/h)을 **같은 도로 위치 구간**으로 비교할 때 쓴다.
같은 위치라도 속도가 다르면 **측정 시간창이 다르므로**, 기준 측정에서 고른 구간의 위·경도를
다른 측정의 같은 위치 시간으로 매핑해야 한다. Distance 채널이 없어도 되고, 이후 분석이
시간축이든 거리축이든 무관하다.

절차:

1. **기준 측정**(예: 100_GPS)을 Graphic Output → `open_gps_map()`로 GPS 맵 열기 → 맵/그래프에서
   구간 선택 → `read_viewer_cursors()`로 `t1`/`t2` 획득.
2. `gps_match_segment(ref_measurement="GPSDATA/100_GPS", t1, t2,
   target_measurements='["GPSDATA/80_GPS","GPSDATA/120_GPS"]')` 호출.
   - 반환: 각 타깃의 `track_start`/`track_stop`(그 측정에서 같은 위치의 시간창) + `match_m`(A/B
     지리 오차, m). BusData NMEA($GPRMC) + theader `starttime`를 디스크에서 직접 읽어 계산한다
     (t_meas = fix UTC − starttime).
3. **`match_m` 확인**: 수 m면 같은 위치(OK). 수십 m 이상이면 그 타깃이 해당 지점을 안 지났을 수
   있으니 신뢰 전에 점검.
4. 분석 — **한 번에 구성하고 출력도 한 번**(권장): `output_rms`의 각 row에 **개별
   `track_start`/`track_stop`**을 실어 15행(속도3 × 채널5)을 **단일 호출**로 렌더한다. 속도별로
   다이어그램을 나누려면 각 row의 `diagram`을 1/2/3으로 준다. 예:
   ```json
   [{"row":1,"diagram":1,"curve":1,"measurement":"GPSDATA/80_GPS","position":"CH1",
     "direction":"S","quantity":"Sound Pressure","track_start":"29.375","track_stop":"61.375"},
    {"row":6,"diagram":2,"curve":1,"measurement":"GPSDATA/100_GPS","position":"CH1",
     "direction":"S","quantity":"Sound Pressure","track_start":"23.713","track_stop":"49.213"},
    {"row":11,"diagram":3,"curve":1,"measurement":"GPSDATA/120_GPS","position":"CH1",
     "direction":"S","quantity":"Sound Pressure","track_start":"19.76","track_stop":"41.26"}, ...]
   ```
   `output_rms(rows=..., band_from="0", band_to="3000", deactivate_beyond=20)` — 한 페이지에 세 속도가
   각 다이어그램/시간창으로 한 방에 나온다. (row별 `track_*`가 전역값을 덮어씀.)
   페이지를 나눠 보존하고 싶을 때만 `new_page` 후 호출한다. **여러 번 output 하지 말 것.**

> 기준 측정 구간은 반드시 그 측정에서 골라야 정확하다(각 측정의 GPS·시간 원점이 다를 수 있음).
> 검증됨: 100_GPS t=7.125~37.5s → 80_GPS 8.505~46.505s(오차 8~9 m), 120_GPS 5.76~31.26s(오차
> 2~3 m); 세 구간 실거리 ≈860 m로 동일, 평균속도 80/100/120에 일치.
