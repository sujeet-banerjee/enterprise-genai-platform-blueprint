# Security policy

## Supported versions

This is a reference implementation, not a supported product. Security fixes land on
`main`; there are no maintained release branches, backports, or long-term-support
versions.

| Version | Security fixes |
| --- | --- |
| `main` | Best effort |
| Older commits / forks | Not supported |

## Reporting a vulnerability

Use **GitHub private vulnerability reporting** on this repository's Security tab
("Report a vulnerability"). Do not open a public issue with exploit details, secrets, or
a working proof of concept.

Include, where possible:

- the affected commit on `main`;
- the endpoint, command or config that triggers the issue;
- reproduction steps and observed impact;
- any suggested fix or mitigation.

## What to expect

This project is maintained on a best-effort basis by the repository owner. There is
**no SLA, no bug bounty, and no commercial support**. Reports are acknowledged and
triaged when time permits; qualifying fixes are prepared privately and announced after
a fix is available. Credit is given on request.

## Scope

In scope: the application code in `app/`, `core/`, the shipped `config/` defaults, and
the delivery artifacts in `deployment/`.

Out of scope: vulnerabilities in third-party models, providers, GitHub, Hugging Face,
or infrastructure you operate; findings that require a configuration the documentation
already labels insecure (for example identity, RBAC and guardrails left disabled on an
internet-facing deployment - see the [security posture](docs/security/README.md)); and
denial-of-service by sheer volume against a demo deployment.

The current threat model, validated controls, open findings and reproduction commands
live in [docs/security/README.md](docs/security/README.md).
