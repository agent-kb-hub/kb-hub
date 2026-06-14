# Security Baseline Design

## Goal

Make Knowledge Hub safe enough for internal deployment by fixing token exposure, completing the admin login bootstrap path, adding automated tests, and aligning runtime behavior with documented configuration.

## Scope

This phase focuses on the smallest set of changes that materially improves product quality:

- Protect token listing behind admin authorization.
- Stop recommending token-in-URL access for administrative workflows.
- Initialize an admin password hash during install.
- Add a reproducible Python dependency file and pytest baseline.
- Use configured local database paths instead of hard-coded workspace paths.
- Apply the same quality gate to sync ingestion that normal ingestion uses.
- Make rate limiting respect configuration.

Large UI redesign, database replacement, multi-user RBAC expansion, and full module decomposition are intentionally deferred.

## Architecture

The application remains a FastAPI single-process service backed by TinyDB. Security-sensitive helper functions stay close to existing code to minimize churn, but tests exercise the public HTTP surface via FastAPI `TestClient`.

Configuration remains file-based through `config.json`. Runtime defaults are centralized so missing optional fields do not crash the service, while deployment scripts generate the required secure fields.

## Behavior

- `/tokens` requires an authenticated admin, either via admin session cookie or a legacy admin bearer token.
- Reader and writer tokens cannot list all node tokens.
- `/sync` rejects low-quality and oversized records using the same checks as `/ingest`.
- Rate limit count and window come from `config.json`, falling back to current defaults.
- Usage tracking and local sync use `local_db_path` from config when present.
- `install.sh` creates a hashed admin password and does not rely on a missing `admin_users` block.

## Testing

Tests create temporary config and database files, import the app with patched paths, and use `TestClient` to verify:

- Public health endpoint works.
- `/tokens` is not public.
- Admin bearer token can list tokens.
- Non-admin tokens cannot list tokens.
- `/sync` rejects low-quality items.
- Rate limiting honors configured values.

