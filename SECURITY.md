# Security Policy

## Supported versions

Security fixes are currently intended for the latest version on the main branch. There are no formal release branches yet.

## Reporting a vulnerability

Please do not publish exploitable vulnerability details, credentials, API keys, or private user data in a public issue or pull request.

Use GitHub's Report a vulnerability option in the repository's Security tab to send a private report, if enabled. Include:
- A clear description of the issue and its potential impact.
- Steps to reproduce in a safe test environment.
- Affected files, versions, and configuration.
- Any suggested mitigation.

If private vulnerability reporting is unavailable, contact the repository maintainer privately through GitHub and ask for a secure reporting channel.

Please allow time for the maintainer to investigate before publicly disclosing an unpatched issue.

## Secrets and local data

Never commit .env, API keys, passwords, access tokens, private conversation histories, clipboard contents, or unredacted activity logs. If a credential is exposed, revoke or rotate it immediately.
