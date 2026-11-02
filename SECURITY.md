# Security Policy

## Supported versions

Only the latest release and `main` get security fixes.

## Reporting a vulnerability

Please **don't** open a public issue for security problems.

Report it privately instead:
[open a security advisory](https://github.com/krnblds/pigment/security/advisories/new).

Please include:

- what the problem is and what it lets someone do;
- steps or a file that reproduces it (for example a crafted model, texture or `.pigment` project);
- the Pigment version or commit, and your OS.

You'll get a reply within a week. Once it's fixed, you'll be credited in the release notes
unless you'd rather not be.

## Worth knowing

- Pigment opens model, image and project files. Treat files from strangers like any other download.
- The MCP server (`pigment-mcp`) can read and write files on your machine. Only connect it to
  agents and clients you trust.
