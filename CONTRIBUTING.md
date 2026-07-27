# Contributing to PAK MCP

Thanks for your interest! PAK MCP is open source so users can extend it and build
their own tools around Müller-BBM PAK.

## Ground rules

- **Never commit secrets or machine-specific config.** `claude_desktop_config*.json`,
  API keys, tokens, and personal paths are git-ignored — keep it that way. Use
  `config.example.json` with placeholder paths for anything shared.
- **Do not commit vendor files.** PAK / Müller-BBM internals (e.g. Tcl init files,
  COM type-library dumps) must not be redistributed. Reference them by path only.
- **Do not commit measurement data or outputs** (`*.dat`, `*.atf`, `*.uf`, `*.png`).

## Development

- Requires Windows + PAK 6.4 + Python 3.10+ (the COM bridge cannot run without a
  local PAK install), so most testing is manual against a running PAK.
- Keep the three servers (`pak_graphdef_mcp.py`, `pak_browser_mcp.py`,
  `pak_arithmetic_mcp.py`) at the repo root so existing client configs keep working.
- Preserve **backward compatibility**: new tool arguments should be optional and
  default to current behavior.

## Verifying a change

Because PAK output is drawn on the graph (not always returned as data), verify by
running the same rows before/after and confirming the **RMS values / curves are
identical**. Capture a screenshot when a numeric readback is needed.

## Pull requests

1. Fork and create a feature branch.
2. Keep changes focused; describe what you tested against which PAK version.
3. Open a PR against `main`.

## Reporting issues

Open a GitHub issue with your PAK version, Python version, the tool call, and the
exact error text (redact any paths/tokens).
