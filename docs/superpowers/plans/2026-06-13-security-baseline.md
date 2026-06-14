# Security Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Knowledge Hub safe enough for internal deployment by fixing token exposure, admin bootstrap, configuration correctness, and adding tests.

**Architecture:** Keep the existing FastAPI/TinyDB single-file service for this phase. Add focused pytest coverage around HTTP behavior and make small, low-risk code changes in place.

**Tech Stack:** Python 3.11+, FastAPI, TinyDB, Uvicorn, Requests, Pytest, HTTPX.

---

### Task 1: Test And Dependency Baseline

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `tests/test_security_baseline.py`

- [ ] Add pinned dependency ranges for runtime and tests.
- [ ] Build pytest fixtures that create temporary config and TinyDB files.
- [ ] Write failing tests for `/tokens` authorization, `/sync` quality gating, and configurable rate limits.

### Task 2: Secure Token Listing

**Files:**
- Modify: `hub_server.py`
- Modify: `README.md`
- Modify: `README.zh.md`

- [ ] Require admin authorization for `/tokens`.
- [ ] Preserve legacy admin bearer token compatibility for API clients.
- [ ] Update documentation so token listing and admin operations are described as protected.

### Task 3: Configuration Correctness

**Files:**
- Modify: `hub_server.py`
- Modify: `config.example.json`

- [ ] Make rate limit count and window read from config.
- [ ] Replace hard-coded local knowledge DB paths with `local_db_path`.
- [ ] Keep defaults compatible with existing deployments.

### Task 4: Sync Quality Gate

**Files:**
- Modify: `hub_server.py`
- Test: `tests/test_security_baseline.py`

- [ ] Apply size and quality checks to `/sync`.
- [ ] Return skipped details for rejected records.
- [ ] Keep valid sync behavior unchanged.

### Task 5: Admin Bootstrap And Scripts

**Files:**
- Modify: `install.sh`
- Modify: `start.sh`
- Modify: `README.md`
- Modify: `README.zh.md`

- [ ] Generate a random admin password when one is not provided.
- [ ] Store only the salted hash in `config.json`.
- [ ] Ensure `start.sh` creates the logs directory before redirecting output.
- [ ] Document admin login and secret handling.

### Task 6: Verification

**Files:**
- Modify as needed based on test results.

- [ ] Run `python3 -m py_compile hub_server.py hub_sync.py scripts/reclassify_v6.py i18n/__init__.py`.
- [ ] Run `python3 -m pytest -q`.
- [ ] Run `git status --short` and summarize changed files.

