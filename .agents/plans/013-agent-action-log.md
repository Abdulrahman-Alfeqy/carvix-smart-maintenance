# Plan: AgentActionLog Foundation + Administrator Inspection

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Arwa
- Reviewer: Abdalrahaman Atef
- Branch: feature/agent-action-log
- Created: 2026-09-27
- Last updated: 2026-09-27

## Objective

Add the SRS-defined AgentActionLog persistence foundation and read-only Administrator inspection in `apps.ai_agent`. Record an identified user, tool, sanitized JSON arguments and result, result status, nonnegative execution duration in milliseconds, and server-generated creation time. Permit only authorized domain Administrators to inspect logs through Django Admin; do not add AI or tool execution behavior.

## Requirements Covered

- SRS Table 10 / §6: AgentActionLog fields are `id`, `user_id`, `tool_name`, `arguments`, `result`, `status`, and `created_at`; user references User; JSON data is structured; user/tool/time are indexed.
- SRS §6.3: AgentActionLog is read-only to non-administrators.
- SRS §8.6: every attempted tool execution is auditable with user, tool, sanitized arguments, result, status, and timestamp.
- SRS FR-31: record tool name, arguments, user, result, status, and time for each attempted tool execution.
- SRS FR-32: structured results expose a success indicator and result details; the log status must agree with its result's `success` boolean.
- SRS FR-35 (Should): Administrator can inspect activity records.
- NFR-M01: keep the foundation within `apps.ai_agent`.

## Current-State Analysis

- `apps/ai_agent` is a scaffold and is not installed in `config/settings.py`; `apps/ai_agent/apps.py` has the incorrect import name `ai_agent` instead of `apps.ai_agent`.
- `models.py`, `admin.py`, and `tests.py` contain only placeholders; the migrations package has no migration.
- The custom User is `apps.authentication.User` with OWNER, TECHNICIAN, and ADMINISTRATOR roles; domain role does not imply `is_staff` or `is_superuser`.
- Existing domain foreign keys use `PROTECT` for historical references.
- `docs/README.md` establishes `docs/CARVIX_SRS_Group6.docx` as authoritative. The supporting legacy ERD's differently named `AUDIT_LOG` does not override the SRS AgentActionLog definition.
- SRS does not define status values or duration. Minimal status vocabulary will be SUCCESS/FAILURE, consistent with FR-32's boolean success; status/result consistency will be enforced. `duration_ms` is included because the task requests execution duration and is constrained nonnegative. No session, correlation, error-code, or extra identity fields are introduced.

## Scope

Create only the AgentActionLog model, schema migration, deterministic payload sanitizer, read-only and domain-Administrator-gated Django Admin registration, app registration/config correction, focused tests, and this plan's implementation report.

## Out of Scope

No maintenance or inventory changes/workflows/tests; no appointment transition or Plan 012 work; no seed-data changes; no AI tools, tool registry, LLM, Chat UI, sessions, orchestration, tool execution, or log-writing integration; no unrelated authentication or UI changes; no new roles or general RBAC work.

## Proposed Changes

- `config/settings.py`: register `apps.ai_agent.apps.AiAgentConfig` so the model and migration are active.
- `apps/ai_agent/apps.py`: correct the app name to `apps.ai_agent`.
- `apps/ai_agent/models.py`: add AgentActionLog with required SRS data, required User FK using PROTECT, SUCCESS/FAILURE status, nonnegative duration_ms, server timestamp, JSON payload checks/sanitization, named database constraints, deterministic ordering, and user/tool/time index.
- `apps/ai_agent/sanitization.py`: add a non-mutating recursive sanitizer for JSON-native dict/list data; redact sensitive-key values deterministically and reject unsupported/non-JSON values.
- `apps/ai_agent/admin.py`: register the model read-only; require both the normal Django Admin view permission and domain ADMINISTRATOR role. Do not grant staff/superuser privileges from the domain role.
- `apps/ai_agent/migrations/0001_initial.py`: generate and inspect the initial schema migration.
- `apps/ai_agent/tests.py`: add model, constraints, sanitizer, role/read-only Admin coverage.
- `.agents/plans/013-agent-action-log.md`: record final actual implementation and validation after all gates pass.

## Backend and Data Rules

- The log's `user` is required and is the authenticated actor supplied by future backend tool execution; no AI/client user identity is added by this task.
- `arguments` and `result` must be top-level objects containing JSON-compatible values. Redaction is recursive and case-insensitive for password, secret, API key, token, authorization, cookie/session credential, and database-credential key variants. Redaction replaces values with `[REDACTED]`; input structures are not mutated.
- Unsupported Python values and non-string object keys are rejected rather than stringified.
- `result.success` must be a boolean matching `status` (true => SUCCESS, false => FAILURE).
- `duration_ms` is a nonnegative integer; `created_at` is server-generated and immutable on normal updates.
- Database check constraints provide defense in depth for status and duration. User deletion is protected to preserve audit history.

## Administrator Inspection Rules

- Django Admin access requires ordinary Django admin authentication/permissions plus `user.role == ADMINISTRATOR`.
- Do not automatically change `is_staff`, `is_superuser`, or permissions based on domain role.
- No add, change, or delete permissions; all fields are read-only; list view exposes only safe identifying metadata and not raw argument/result payloads by default. Authorized detail inspection may display sanitized JSON.
- OWNER, TECHNICIAN, and non-admin staff cannot inspect the records.

## Test Plan and Acceptance Criteria

- Required User relationship; User deletion raises protection; timestamp is generated; deterministic newest-first ordering with a stable tie-breaker.
- Valid SUCCESS and FAILURE data accepted; inconsistent result/status, unsupported status, negative duration, and malformed payloads rejected.
- PostgreSQL enforces named status and duration constraints independently of model validation.
- Arguments/results round-trip as JSON and sanitizer redacts required sensitive keys recursively, is deterministic, does not mutate inputs, and rejects non-JSON-native values.
- Admin model is registered, read-only, and only viewable by a domain Administrator who also satisfies Django Admin's permission gate; non-administrator staff is denied. Domain role does not grant staff/superuser automatically.
- Run Django system check, `makemigrations --check`, focused AgentActionLog tests, relevant auth/Admin tests, full test suite on PostgreSQL, `git diff --check`, and inspect migration and full diff/boundaries. Stop on validation failure; do not claim PostgreSQL success if unavailable.

## Risks and Problems

- Enabling the previously uninstalled app creates the first migration and requires applying it in deployment before code relying on the model is used.
- Sanitization must prevent credential leakage without transforming unrelated values or mutating caller data.
- Admin requires existing Django staff/view permission in addition to domain Administrator role; role alone intentionally does not confer Django Admin access.
- Audit retention is supported through PROTECT but no retention/deletion policy is specified by the SRS.
- Status and duration are minimal explicit task decisions because the SRS does not enumerate them; avoid extra schema fields.

## Alternatives Considered

### Option A — Dedicated model and sanitizer in apps.ai_agent (Recommended)

Implement SRS AgentActionLog as a normal model and use a small recursive sanitizer at the model persistence boundary. Register read-only Admin with a role gate. This gives the requested audit foundation and prevents ordinary persistence paths from bypassing redaction.

### Option B — Reuse supporting ERD AUDIT_LOG or add an execution service

The supporting ERD's legacy AUDIT_LOG has fields absent from the authoritative SRS, and no execution workflow is in scope. Reusing it would conflict with SRS naming/schema; adding execution service behavior would expand scope.

## Recommended Approach

Use Option A. Follow the authoritative SRS field contract, existing custom User and PROTECT convention, and task-specific duration/status needs. Add no tool or AI execution integration.

## Implementation Steps

1. Create this plan with the supplied approval metadata.
2. Register the app and correct its AppConfig import path.
3. Implement the AgentActionLog model and sanitizer; generate and inspect its migration.
4. Add read-only role-gated Admin and focused tests.
5. Run the specified checks in order, inspect the complete diff and boundaries, then accurately record results here and mark IMPLEMENTED only if all required gates pass.

## Migration and Environment Impact

One initial migration creates the AgentActionLog table, status/duration constraints, and user/tool/time index. It depends on the swappable custom User model. No dependency, setting secret, or environment variable changes. No migration is applied to a persistent database without the required human approval described in repository workflow.

## Open Questions

None blocking. Task-provided requirements resolve the scope; minimal SUCCESS/FAILURE status and nonnegative `duration_ms` are explicitly documented design choices.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-27

## Implementation Report

- **Summary:** Added the SRS-aligned `AgentActionLog` persistence foundation and read-only, role-gated Django Admin inspection. The model stores a required protected User reference, tool name, recursively sanitized JSON arguments/result, SUCCESS/FAILURE status consistent with `result.success`, nonnegative `duration_ms`, and server-created timestamp. Added status/duration database checks and a composite user/tool/time index. No tool execution or AI integration was added.
- **Files created:** `.agents/plans/013-agent-action-log.md`; `apps/ai_agent/migrations/0001_initial.py`; `apps/ai_agent/sanitization.py`.
- **Files modified:** `config/settings.py`; `apps/ai_agent/apps.py`; `apps/ai_agent/models.py`; `apps/ai_agent/admin.py`; `apps/ai_agent/tests.py`.
- **Tests executed:** `.venv\Scripts\python.exe manage.py check`; `.venv\Scripts\python.exe manage.py makemigrations --check`; `.venv\Scripts\python.exe manage.py test apps.ai_agent.tests -v 2`; `.venv\Scripts\python.exe manage.py test apps.authentication.tests -v 2`; `.venv\Scripts\python.exe manage.py test -v 2`; and `git diff --check`.
- **Test results:** Focused AgentActionLog tests: 15/15 passed. Existing authentication tests: 65/65 passed. Complete project suite on PostgreSQL: 224/224 passed. Django system check reported no issues; `makemigrations --check` reported no changes; `git diff --check` exited 0 with no whitespace errors (Git emitted only line-ending conversion warnings).
- **Migration/environment changes:** Added `apps/ai_agent/migrations/0001_initial.py` with a swappable User dependency, PROTECT foreign key, approved fields, named status and duration checks, and user/tool/time index. The migration was exercised by Django's PostgreSQL test database. No dependencies, secrets, or environment variables changed. No persistent local database migration was run as part of validation.
- **Security checks:** Domain Administrator role is required in addition to ordinary Django Admin view permission. Add/change/delete are denied, all fields are read-only, and domain role does not grant `is_staff` or `is_superuser`. Owner/Technician staff are denied. User identity is a required database relation and cannot be deleted while logs reference it. Sanitization recursively redacts sensitive key values, rejects unsupported JSON values, and does not mutate caller payloads.
- **Migration inspection:** Confirmed the initial migration contains only AgentActionLog and its approved database structures; it does not alter existing models.
- **Scope boundary:** No maintenance, inventory, appointment, seed-data, authentication source, settings other than app registration, or AI execution workflow was changed. No model outside AgentActionLog was modified.
- **Remaining risks:** The SRS does not define audit retention/deletion policy or status vocabulary. This plan uses the documented minimal SUCCESS/FAILURE values and `duration_ms`; audit retention beyond protected user history remains a future policy decision. Future tool execution must call this model and supply the authenticated actor; execution integration is deliberately deferred.
- **Deviations from plan:** None.
- **Result:** Implementation and required validation are complete. No Git staging, commit, push, merge, or pull request was performed.
