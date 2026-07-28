# Changelog

All notable changes to **PAK MCP** are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/), and this
project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-07-29

### Added
- **`run_analysis` chaining tool.** One call chains
  `reset → configure many rows (analysis families may be mixed) → apply layout →
  Graphic Output → screenshot → server-side verification`, replacing the sequence
  `reset_graphdef + configure_*_rows + graphic_output + capture_viewer`. Supported
  per-row `analysis` values: `aps`, `octave`, `overall`, `orderaps`,
  `ordercomplex`, `detector` (with `track_preset` distance/speed/time). Sound
  Pressure channels are auto A-weighted; vibration stays linear. RMS band-pass
  tables remain in `output_rms`.
- **Sidecar result files.** `run_analysis` writes `run_analysis_progress.json`
  (live progress) and `run_analysis_result.json` (final `verification`, `warnings`,
  capture path, `done: true`). A large single call may exceed the MCP client
  response timeout, but PAK still finishes — these files let the run be confirmed
  afterward, so a timeout is no longer a failure.
- **Inline screenshot capture.** New tool `capture_viewer_inline` and a
  `run_analysis(inline_capture=True)` option return the screenshot embedded in the
  response (base64 MCP Image). The server reads the PNG it just wrote, so the image
  renders directly in chat **without the client needing filesystem access to the
  capture path** — fixes "path not accessible" in the plain chat client.

### Changed
- **Capture degrades gracefully.** `_capture_viewer` never raises; on missing
  `pillow`/`uiautomation`, no Graphic Viewer window, or a headless/no-display
  session it returns an actionable message and the analysis/render still completes
  (only the screenshot is skipped). Clarifies that capture needs the local desktop
  MCP host (not web/mobile chat).
- **Dependencies auto-install.** `requirements.txt` now pulls `pillow` and
  `uiautomation` (Windows-only marker) so `pip install -r requirements.txt` sets up
  screen capture. On non-Windows, `uiautomation` is skipped and capture degrades.

### Docs
- `skills/pak-nvh/SKILL.md`: new `run_analysis` section + a 2-step verification
  procedure (read `run_analysis_result.json` for completion/verification, then read
  the PNG for the visual check) and chunk-vs-single-call guidance.
- `docs/PIPELINE.md`: added the layout rule (RMS → `RMS.vas_dly`, everything else →
  `standard.vas_dly`) and unified the capture filename to `view_shot.png`.
- `.gitignore`: ignore runtime sidecars (`run_analysis_*.json`) and temporary
  row-JSON files.

### Notes
- The single-COM-connection constraint is unchanged: run tools sequentially. For
  large jobs, either chunk into ~15–20 rows per call, or make one big
  `run_analysis` call and confirm via the sidecar result file after PAK finishes.

## [0.1.0] — Initial public release

### Added
- MCP servers **PAK** (Graphic Definition automation, `output_rms` band-pass RMS
  table, `ensure_rms_layout`, `set_layout_mode`, `reset_graphdef`, pages) and
  **PAK_Browser** (current project, measurements, channel lists) driving PAK 6.4 via
  the official Tcl COM bridge.
- Analysis tools: APS (2D/3D), 1/1·1/3 Octave, Overall/Sum level, Order APS, Order
  complex, Detector (exterior/pass-by with distance/speed/time tracks), plus the
  band-pass RMS table workflow.
- `pak-nvh` skill and project documentation.

[0.2.0]: https://github.com/seungchan99/pak-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/seungchan99/pak-mcp/releases/tag/v0.1.0
