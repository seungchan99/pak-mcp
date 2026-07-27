# MCPB bundle (one-click install) — starter

This folder is a **starter** for packaging PAK MCP as an MCPB bundle so users can
install it in Claude Desktop without hand-editing `claude_desktop_config.json`.

> Status: scaffold — needs `mcpb` CLI + local testing before publishing.

## Notes

- An MCPB manifest describes **one server**. This `manifest.json` covers the main
  `PAK` (graphdef) server. To bundle `PAK_Browser` and `PAK_Arithmetic` too,
  create a manifest per server (or a combined bundle once you've validated the
  multi-server layout with your MCPB CLI version).
- The server files must be included in the bundle (copy them next to the manifest,
  or adjust `entry_point`/`args` paths).

## Build & test

```powershell
npm install -g @anthropic-ai/mcpb   # or the current mcpb CLI
cd packaging\mcpb
# copy the server(s) you want to bundle into this folder first
mcpb pack
```

This produces a `.mcpb` file users can drag into Claude Desktop → Settings →
Extensions to install. Verify tools appear and PAK responds before distributing.
