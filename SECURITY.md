# Security Policy

## Reporting a vulnerability

Please report security issues privately rather than opening a public issue.
Use GitHub's **"Report a vulnerability"** (Security tab → Advisories) or email the
maintainer. We aim to acknowledge reports within a few business days.

## Scope & notes

- These servers automate a **locally installed PAK** over COM. They run with the
  privileges of the user who launches them and can read/write PAK projects and
  files on that machine — treat them like any local automation tool.
- **No secrets in the repo.** Machine-specific config (`claude_desktop_config*.json`),
  tokens, and API keys are git-ignored. If you find a committed secret, report it
  and it will be removed and rotated.
- **No vendor redistribution.** The project does not ship PAK / Müller-BBM files;
  it only calls a PAK install already present on the machine.
- Only expose these MCP servers to trusted MCP clients on trusted machines.
