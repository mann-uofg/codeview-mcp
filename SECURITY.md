# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's private
[security advisory form](https://github.com/mann-uofg/codeview-mcp/security/advisories/new) instead.
You should get a response within a few days. Once a fix is released you'll be credited unless you prefer not to be.

## Supported versions

| Version | Supported |
|---|---|
| 2.x | ✅ |
| 1.x (`reviewgenie-mcp`) | ❌ |

## Threat model

ReviewGenie treats diffs, pull-request text, repository contents and model output as untrusted.
The README's [Security model](README.md#security-model) section lists the mitigations. Reports about
bypassing any of them (prompt injection that leads to posting attacker-controlled content, code execution
through repository configuration, token exfiltration, SSRF) are especially welcome.
