# Security Policy

## Reporting a vulnerability

This is a public Foundry-Studio repo containing a multi-tenant data platform with PostgreSQL Row-Level Security (RLS). Vulnerabilities — particularly RLS bypass, tenant data leakage, or schema-level isolation breaks — are taken seriously.

**To report a vulnerability privately:**
- Email: tim@foundry-studio.com
- Subject prefix: `[foundry-cip security]`
- Or: use GitHub's [private vulnerability reporting](https://github.com/Foundry-Studio/foundry-cip/security/advisories/new)

**Please include:**
- Affected version of foundry-cip (or git SHA)
- Affected component (orchestrator, persister, RLS policy, specific migration, etc.)
- Description of the vulnerability
- Steps to reproduce
- Expected vs actual behavior
- Severity assessment if you have one

We will acknowledge receipt within 3 business days and provide a status update within 7 business days.

## Disclosure policy

We follow coordinated disclosure:
1. Receive private report.
2. Confirm and assess.
3. Develop fix in a private branch / private security advisory.
4. Issue patched version.
5. Publish advisory + credit reporter (if reporter consents).

We aim for a 30-day window from confirmation to public advisory unless the vulnerability is already public, in which case we expedite.

## Scope

In scope:
- The `cip` Python package (orchestrator, framework, persister, validation)
- The Alembic migrations in `migrations/versions/`
- Documentation that prescribes a security-relevant pattern (RLS policies, `SET LOCAL app.current_tenant`, authority levels)

Out of scope:
- Foundry-Agent-System (the source monorepo) — report to that repo's security policy
- Vulnerabilities in pinned dependencies (sqlalchemy, alembic, psycopg) — please report upstream first
- Misuse / misconfiguration by consumers (example: a venture's connector that bypasses tenant scoping intentionally)

## Hall of fame

When a researcher reports a confirmed vulnerability and consents to credit, their name + handle land here.

(empty as of 2026-04-27)
