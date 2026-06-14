# Test Report

Date: 2026-06-14
Branch: `product-hardening-sqlite-admin-security`

## Scope

This report covers the local product-hardening update for Knowledge Hub:

- Security baseline for admin-only APIs and dashboard token URL mitigation.
- Modularized backend helpers under `knowledge_hub/`.
- SQLite storage backend and TinyDB-to-SQLite migration.
- Attachment parsing and local attachment path policy.
- Automatic classification, tags, entities, and explainable quality details.
- Admin item update/delete/list APIs and storage maintenance endpoint.
- Docker/manual deployment documentation and examples.

## Commands

```bash
.venv/bin/python -m unittest tests.test_core_modules -v
```

Result:

```text
Ran 66 tests in 0.063s
OK
```

```bash
.venv/bin/python -m pytest tests/test_security_baseline.py -q
```

Result:

```text
13 passed in 0.54s
```

```bash
.venv/bin/python -m py_compile hub_server.py hub_sync.py scripts/reclassify_v6.py scripts/migrate_to_sqlite.py i18n/__init__.py knowledge_hub/*.py
```

Result: passed.

```bash
.venv/bin/python -m json.tool config.example.json >/dev/null
.venv/bin/python -m json.tool config.docker.example.json >/dev/null
git diff --check
```

Result: passed.

## Verified Behaviors

- SQLite store inserts, deduplicates, reads, updates, deletes, updates usage counters, and runs integrity/VACUUM maintenance.
- TinyDB-to-SQLite migration is idempotent.
- `/tokens` and admin APIs require admin authorization.
- Admin bearer fallback works only for admin-role node tokens.
- Dashboard legacy token URL flow exchanges token for a short-lived cookie and redirects to `/dashboard`.
- Admin list filtering/pagination works through dedicated server-side logic.
- Quality validation returns explainable `quality_detail.reasons` on rejection.
- Attachment path validation enforces allowed directories, suffixes, and size limits.
- Query responses expose v2 knowledge metadata without returning full content unless requested.

## Not Verified Here

- Public internet access, DNS, HTTPS, and reverse proxy behavior.
- Browser-level Cookie `Secure` behavior under a real production domain.
- Long-running service behavior over multiple days.
- Large production datasets with hundreds of thousands of knowledge records.
- Docker Compose runtime, because this environment does not provide a Docker Compose validation target.
