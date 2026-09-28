# Security policy

Please don't open a public issue for security problems. Report them privately through
[GitHub security advisories](https://github.com/mann-uofg/codeview-mcp/security/advisories/new).
I'll reply within a few days.

Only the latest version on `main` gets fixes.

codeview treats diffs, PR titles and descriptions, repository contents and model output as untrusted input.
The mitigations are listed under "Security notes" in the README. I'm especially interested in reports of:

- prompt injection that gets attacker-controlled text posted to a PR
- code execution through repository configuration
- token leakage or SSRF
