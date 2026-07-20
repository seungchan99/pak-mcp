---
name: "pak-nvh"
description: "Drive the PAK NVH MCP tools (PAK, PAK_Browser, PAK_Arithmetic) to build Graphic Definitions, output band-pass RMS tables, and build 2D comparison plots (overlaying several measurements/channels as APS/Octave curves). Use whenever the user asks to compute or output RMS, band-pass RMS, RMS 값/표, compare/비교 measurements, load PAK measurements/channels, set up APS/Octave/Order analyses, or run PAK Graphic Output. IMPORTANT: in PAK, 'RMS 분석' means band-pass RMS (Sum level 1 = Bandpaß mag) drawn as a TABLE on the graph via the RMS.vas_dly LAYOUT and read back from a screenshot — it is NOT a separate arithmetic/analysis. Always drive it through the output_rms tool, never by hand-configuring rows."
---

# PAK NVH automation

These MCP servers are always available in every Claude Desktop window:

- **PAK** — Graphic Definition automation + `output_rms` (band-pass RMS table) + `ensure_rms_layout` + `set_layout_mode` + `reset_graphdef`.
- **PAK_Browser** — read the current project, measurements, and channel lists.
- **PAK_Arithmetic** — build arithmetic formulas (separate feature; not RMS).

PAK allows only **one** COM connection at a time, so run tools sequentially, not in parallel.

## Presenting data & channel info: ALWAYS use tables

Whenever you load or report project data (measurements) or channel info
(`PAK_Browser.list_project_data`, `list_last_measurements`, `get_channels`), present
the results to the user as **markdown tables** — never as bullet lists or prose.

- **측정 데이터 목록**: a table of measurements (`#`, `측정 이름`, and any relevant test/subtitle columns).
- **채널 목록**: a table with columns `Nr | Label | Dir | Quantity | 분류` (분류 = 진동/소음/자속/전류/CAN …).
- Add a short **요약 table** grouping channels by quantity (분류, 채널 수, 채널) when there are many channels.
- Keep Sound(소음) and Vibration(진동) distinguishable in the 분류 column (see the Sound vs Vibration rule below).

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

Noise/sound analysis is (almost) always done **A-weighted**. `output_rms` therefore
**auto-applies A-weighting to every Sound Pressure channel**. You do not need to ask or
set it — sound rows come out dB(A) by default; vibration rows stay linear.

> The frequency weighting is set via **`Item.DarstFilter.Fweight = "A"`** (the
> Display/Filter → Freq. weighting field). This is the ONLY writable + effective path:
> `Datentyp.Tp2det_fweight` is writable but a **no-op** for the RMS (verified: A vs lin
> gave identical 84.0), and `GesPegel.N1fbew` is **read-only** in every state. With
> `Item.DarstFilter.Fweight = A` the axis becomes dB(A) and the RMS drops correctly
> (e.g. 84.0 → 62.3). `DarstFilter` is an Item sub-object, so release Datentyp /
> GesPegel / TrackingParams before opening it. `output_rms` handles all this.

- Override globally: `weighting="A"|"B"|"C"|"lin"` (applies to ALL rows).
- Disable the sound auto-rule: `sound_weighting=""` (or `"lin"`).
- The response echoes each row's applied `weighting` so you can confirm sound rows say `A`.

For non-RMS work, apply weighting per row with `set_weighting(row, "A")` or
`configure_row(..., weighting="A")`.

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

## Other analyses (not RMS)

- Standard APS/Octave spectra (single curve per diagram): `configure_rows` (auto 32768 /
  blocksize 16384; supports x_from/x_to, y_type, A-weighting). No `stat_parameter` — for
  overlays use `configure_row` (see Comparison output).
- Order analysis (차수):
    - **Order APS** (order-frequency colormap): `configure_orderaps_rows` (Pdtype "Order APS",
      RPM track, `x_from`/`x_to` for the displayed order range).
    - **Order complex** (특정 차수 magnitude vs RPM): `configure_ordercomplex_rows` (order number,
      RPM track, X-axis always reset to auto).
    - **Maximum order** = the WRITABLE property **`Datentyp.Tp2spec_maxorder`** (the Data-type tab
      "Maximum order" field). Do NOT use `Item.Order.Ordto` for max order — it is **read-only** in
      this graphic definition and raises `Value can only be read`. Order Lines / Order Resol. are
      derived from blocksize + max order (do not set them). Blocksize = `Tp2spec_blocksize`.
- CAN signals (RPM/Torque/SOC/속도, value vs Time): `configure_can_rows`.
- Reset: `reset_graphdef` (Ctrl+N). Pages: `list_pages` / `new_page` / `goto_page` / `delete_page`.
- Save/open: `save_graphdef` / `open_graphdef_file` / `list_graphdefs`.
- Working mode: `get_working_mode` / `set_working_mode`.

## GPS 포지션 (GPS42 G2 — 좌표/속도)

GPS 채널(위도 latitude / 경도 longitude / 속도 speed / 고도 altitude)은 CAN 과 똑같이
**Slow quantity**(Slow throughput → Slow quantity, Srate Original, 평균 없음)로 저장된다.
채널명은 PAK Quantity 카탈로그·측정마다 다르므로 **`PAK_Browser.get_channels` 로 실제
position/direction/quantity 를 반드시 확인**하고 넣는다(direction 은 보통 `S`). 아래 툴
기본값의 quantity 이름("Latitude"/"Longitude"/"Speed")은 예시일 뿐 — 실제 채널명으로 교체.

두 가지 뷰:

- **주행 경로 트랙 (위도 vs 경도, 지도형 궤적)** → `configure_gps_track_row` / `configure_gps_track_rows`.
  위도를 Slow quantity(Y)로, 경도 채널을 **Track(Par.-channel) 축**에 올려 X 축으로 만들어
  두 slow 채널을 서로 교차 플롯 = 차량 궤적. 여러 주행을 같은 diagram 에 curve 로 겹치면
  경로 비교. 예:

  ```
  configure_gps_track_rows(rows='[
   {"row":1,"diagram":1,"curve":1,"measurement":"ROAD_01/Run_01 [CP]",
    "lat_position":"GPS","lat_direction":"S","lat_quantity":"Latitude",
    "lon_position":"GPS","lon_direction":"S","lon_quantity":"Longitude"}
  ]', output=true)
  ```

- **위치·속도 vs 시간/속도** → `configure_gps_row` / `configure_gps_rows`.
  GPS slow 채널을 **시간축**(기본, `track_quantity="Time"`)으로, 또는 **속도 채널**을
  Track 에 올려 vs 속도로 그림. CAN 과 동일 메커니즘(평균 없음, 축 auto). 예:

  ```
  configure_gps_rows(rows='[
   {"row":1,"diagram":1,"curve":1,"measurement":"ROAD_01/Run_01 [CP]",
    "position":"GPS","direction":"S","quantity":"Speed"}
  ]', output=true)   # 속도 vs 시간
  ```

  위도 vs 속도처럼 slow 채널끼리 그리려면 `track_quantity` 를 속도 채널 quantity 로,
  `track_position`/`track_direction` 를 그 채널로 지정.

> 주의: GPS 가 raw BusData(NMEA) 로만 저장된 측정(예: GPSDATA 프로젝트의 80/100/120_GPS)
> 에서는 위/경도가 slow 채널로 안 잡힐 수 있다 — 그 경우 위 track 툴 대신 PAK 내장 GPS
> Map Viewer + 아래 트리거 워크플로를 쓴다.

## GPS 트리거로 분석 구간 지정 (맵 커서 → 시간창 → 구간 RMS)

통과소음 GPS 주행 데이터에서 **원하는 위치 구간만** 분석하는 흐름. PAK 의 GPS Map Viewer는
Graphic Viewer 툴바 **맨 오른쪽 맵(위치 핀) 아이콘**으로 열리며, 호출된 데이터와 **시간·좌표가
동기화**된다. GPS UTC ↔ 측정 시간축은 `theader.xml` 의 `starttime`(=측정 t=0, 트리거) 기준으로
1:1 정렬됨(검증 완료): `t_측정 = GPS_UTC − starttime`.

절차 (자동 클릭 없음 — 사용자가 맵에서 구간 선택, 나머지는 읽기/실행):

1. 해당 측정을 Graphic Output 으로 띄운다(소음 채널 등).
2. 사용자가 맵(또는 커브)에서 **시작·끝 커서**를 찍어 구간을 정한다.
3. `read_viewer_cursors()` 로 커서 시간을 **읽는다** (X1/X2 = 시간). 반환된 `t1`/`t2` 사용.
   - UI Automation 읽기 전용. 커서가 하나면 `t1` 만 오고 `note` 로 두 번째 커서 요청.
4. 그 `t1`/`t2` 를 `output_rms` 의 `track_start`/`track_stop` 에 넣어 **구간 band-pass RMS** 실행:

  ```
  read_viewer_cursors()      # -> {"t1": 12.34, "t2": 23.45, ...}
  output_rms(rows='[
   {"row":1,"diagram":1,"curve":1,"measurement":"GPSDATA/120_GPS [CP]",
    "position":"CH1","direction":"S","quantity":"Sound Pressure"}
  ]', band_from="0", band_to="5000", track_start="12.34", track_stop="23.45")
  ```

RMS 는 `[t1,t2]` 구간만 평균한다(기본 Min/Max = 전체). 소음 채널은 자동 A-weighting.
`read_viewer_cursors` 는 Graphic Viewer 가 열려 있어야 하고, 첫 실측 시 커서 라벨 인식은 라이브로
한 번 확인한다(안 읽히면 커서 패널이 보이게 뷰어를 활성화).

## Channel not recognized after switching data — recommend Auto, ASK don't auto-fix

A row binds a channel by its **exact position/name** (e.g. `CH1`, `Front Right`,
`Gear Lever+X`). When a row (or a whole Graphic Definition) is pointed at a
**different data source whose channel names differ**, the stored name has no match
in the new data, so:

- the Data Definition (Info) column shows the analysis only (`APS (3D)` with no
  `Pos. CHx`), the channel is not read, and nothing is drawn.

The value/data are fine — only the **binding is unresolved**. Only opening the row
dialog, re-selecting a valid channel, and pressing **OK (a UI commit)** refreshes the
Info. `configure_row`/`Graphicoutput` alone do NOT refresh it. And `Graphicoutput`
does **not** raise an error when the channel is unbound, so "output ran = channel
recognized" is FALSE — never judge recognition by Graphicoutput success.

**Trigger this handling when:**

- the user says the channel/data isn't showing — "채널 안 나와", "데이터가 안 떠",
  "인식이 안 돼", "APS 안 나옴", etc.; or
- you configure/switch a row and the recognized channel does not resolve (Info stays
  `... (3D)` with no `Pos.`, or the curve renders empty).

**Do NOT auto-fix.** Never silently switch the channel to `Auto` or change channel
names for the user. Respond in a **question** offering:

1. **Recommend `Auto`** — setting the channel to `Auto` binds the **first valid
   channel** of the current data immediately, with no refresh needed (works regardless
   of naming). A safe starting point; the user then narrows to the specific channel.
2. **Show the recognized/available channels** for that data (`PAK_Browser.get_channels`
   or the data-definition dialog list) as Nr / label / direction / quantity, so the
   user can pick the exact matching name.

Then let the user choose. The two root fixes to surface: enter the **exact channel
name matching the data**, or start with **`Auto`** and then change to the desired
channel. Rule of thumb: "different data = channel names must be re-bound" — Claude
surfaces Auto / recognized channels as a question, never auto-applies.

## 분석 중 새 분석 요청 — 페이지 처리 규칙

Graphic Definition 으로 분석을 진행하던 중 사용자가 **새로운 분석**을 요청하면, 기존
분석을 보존할지 지울지에 따라 처리를 나눈다.

1. **새 페이지 추가로 생성 → 바로 진행 (질문 없이).**
   기존 페이지·분석은 그대로 두고 `new_page` 로 새 페이지를 만들어 거기에 새 분석을
   구성한다. 비파괴적이므로 확인 없이 진행한다. (기본 동작 — 사용자가 "초기화/리셋"을
   명시하지 않는 한 이 방식.)
   - `list_pages` 로 현재 페이지 확인 → `new_page` → 새 페이지에서 configure_*/output_rms.

2. **기존 Graphic Definition 을 초기화(reset)해야 하는 경우 → 반드시 사용자에게 질문.**
   `reset_graphdef` 는 기존 분석/페이지를 지우므로, 실행 전에 **"새 페이지로 추가할까요,
   아니면 현재 정의를 초기화하고 진행할까요?"** 를 질문으로 물어 확인한 뒤에만 초기화한다.
   사용자가 초기화를 고르면 `reset_graphdef`, 추가를 고르면 위 1번(new page)으로 간다.

> 요약: **추가(new page) = 비파괴 → 바로 진행. 초기화(reset) = 파괴적 → 질문 후 진행.**
> 애매하면 초기화하지 말고 새 페이지로 가거나 물어본다.
