# Backend Modularization Design

## Goal

Reduce `hub_server.py` risk by extracting framework-independent business logic into small modules and making the core behavior testable without a running FastAPI service.

## Scope

This stage extracts pure backend logic only:

- Password hashing and verification.
- Knowledge quality scoring.
- Content hashing and in-memory search.
- Configured path resolution.
- Standard-library unit tests for extracted modules.

FastAPI route splitting, template extraction, and database replacement are deferred to later stages because they touch larger behavior surfaces.

## Architecture

The new `knowledge_hub` package contains small modules with no FastAPI or TinyDB dependency where possible:

- `knowledge_hub.security`: password hash helpers.
- `knowledge_hub.quality`: knowledge quality scoring.
- `knowledge_hub.search`: content hash and list search.
- `knowledge_hub.paths`: config path resolution.

`hub_server.py` imports these helpers and keeps API routing unchanged.

## Testing

`tests/test_core_modules.py` uses Python `unittest`, so it can run without installing external dependencies. Existing FastAPI tests remain in place for environments where `requirements-dev.txt` can be installed.

