# Plan: AI Agent Foundation and Authenticated Chat

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/ai-agent-foundation-chat
- Created: 2026-09-27
- Last updated: 2026-09-27

## Objective

Establish the isolated `apps.ai_agent` application boundary with authenticated Chat page and JSON endpoint, safe role-appropriate context, centralized system prompt, provider adapter, explicit empty production tool registry, and focused tests. No real business tools or side effects are included.

## Requirements Covered

- SRS FR-21: asynchronous authenticated conversational interface.
- SRS FR-22: safe role-appropriate context with no other Owner's private data.
- SRS FR-27 through FR-29: authenticated identity binding, argument validation, and permission boundaries for future tools.
- SRS FR-31 and §8.6: auditability applies when a registered tool is actually executed; this foundation registers no production tools.
- SRS FR-32 through FR-34: structured results, no unverified success claims, and safe invalid-input/provider-unavailability behavior.
- SRS §8.1 through §8.6, NFR-U03, and role capability table: CARVIX-specific prompt, context, allowlist, visible pending/failure states, and role scoping.

## Current-State Analysis

- Baseline is clean `feature/ai-agent-foundation-chat` at `b028e49`, the merge of PR #19 and Plan 013. Plan 012 is present through PR #18 merge `450e654`.
- `apps/ai_agent` is installed and contains Plan 013's `AgentActionLog`, initial migration, recursive `sanitize_payload`, read-only Administrator admin, and tests. It has no chat, provider, prompt, context, registry, or audit recording service.
- `AgentActionLog.objects.create(...)` sanitizes arguments/results through model validation; status must match `result.success`, duration is a nonnegative integer, and the model requires the authenticated User relation. Its schema and migration remain unchanged.
- Authentication uses `apps.authentication.User.Role` with OWNER, TECHNICIAN, and ADMINISTRATOR. Existing appointment URLs are namespaced under `appointments`; technician detail uses `appointments:technician-appointment-detail` with `pk`.
- The SRS specifies only safe context needed for the active request; its role table distinguishes Owner's own context, Technician assigned context, and Administrator operational context. Existing models support scoped owner/assigned appointment queries.
- `requirements.txt` contains Django, psycopg, and python-dotenv. No provider SDK or configured provider integration exists; no live provider call is required for this foundation.
- `templates/base.html` exists and is to be extended without modification. No AI routes currently exist. PostgreSQL is configured as the only database.
- No new model, migration, dependency, environment variable, Plan 015 change, or external credential is required.

## Proposed Changes

- `.agents/plans/014-ai-agent-foundation-chat.md`: record approval and, after validation, the implementation report.
- `apps/ai_agent/context.py`: build JSON primitives only; Owner-owned vehicle and upcoming appointment summaries, Technician-assigned appointment summaries (requiring a TechnicianProfile), and bounded Administrator appointment status counts. Use role checks only, never staff/superuser flags; omit notes, credentials, logs, and unrelated records.
- `apps/ai_agent/prompts.py`: central CARVIX system prompt with SRS guardrails.
- `apps/ai_agent/provider.py`: narrow provider protocol and safe unavailable implementation; no SDK, key lookup, SDK object, or network call.
- `apps/ai_agent/tools.py`: explicit empty production mapping and a controlled structured rejection for unregistered names; no dynamic imports/reflection.
- `apps/ai_agent/agent.py`: compose safe context, prompt, provider, optional tool-request parsing, allowlist check, and safe structured response. Provider errors are sanitized. No business tool or data side effect executes.
- `apps/ai_agent/views.py`, `apps/ai_agent/urls.py`, `config/urls.py`: authenticated HTML page and POST-only JSON endpoint; anonymous HTML redirects to login and anonymous JSON receives a stable 401 response. Keep CSRF middleware active.
- `templates/ai_agent/chat.html`, `static/js/agent_chat.js`: isolated semantic Chat UI, rendered namespaced URL, CSRF header, asynchronous fetch, and text-only safe rendering. Do not edit base template or shared CSS.
- `apps/ai_agent/tests.py`: focused tests for roles, privacy, validation, CSRF, response shape, provider seam, registry refusal, page rendering, and no side effects. Reuse Plan 013's model/sanitizer without changing its schema or migration.

## Risks and Problems

- Role context could leak records if queries are not scoped before serialization; tests will use foreign Owner and Technician fixtures and verify their private records are excluded.
- The provider is unavailable by default; endpoint and frontend must make this a safe, visible failure without affecting ordinary workflows.
- JSON endpoints must not bypass Django CSRF middleware; use an enforced-CSRF client for rejection and successful token round-trip coverage.
- Provider-produced tool names and payloads are untrusted. Only the explicit mapping may dispatch; the production mapping is empty and arbitrary names never resolve to callables.
- No chat persistence exists, so the context and message are request-local. This is consistent with the no-conversation-model scope.
- No migration is expected; `makemigrations --check` and migration-directory/diff inspection will verify that.
- Concurrent `feature/frontend-docs-demo-readiness` work owns shared navigation, base template, shared CSS, docs, README, and Plan 015. These are excluded from this task.

## Alternatives Considered

### Option A: Implement isolated provider boundary and empty tool registry now

Advantages: establishes the controlled application boundary and safely validates the end-to-end UI/error path without claiming external LLM availability or enabling business side effects. Disadvantages: users receive provider-unavailable until a separate approved provider integration is configured.

### Option B: Add an LLM SDK and enable a live provider now

Advantages: could return generated responses immediately. Disadvantages: no provider SDK is present or approved in dependencies, credentials are unavailable for this plan, and it expands setup/security/network scope and cannot be reliably validated here.

## Recommended Approach

Choose Option A. The SRS and approved scope permit a safe provider boundary when no SDK exists. This gives the application a testable authenticated contract, keeps non-AI workflows independent, and ensures no unvalidated tool or side effect can execute.

## Implementation Steps

1. Add the approved plan, then implement bounded context, centralized prompt, provider adapter, and explicit empty tool registry.
2. Add namespaced authenticated Chat page and structured POST JSON endpoint with input validation and CSRF.
3. Add isolated ES6 client and focused tests; ensure failures are safe and no production tool executes.
4. Check PostgreSQL availability, run gates in the requested order, inspect migrations and complete diff/scope, then finalize the plan.
5. If every gate and review passes, stage only approved-scope files, commit once with the requested message, push the existing feature branch, and verify clean synchronized state.

## Test Plan

- Chat page redirect for anonymous and access for all three domain roles independent of `is_staff`/`is_superuser`.
- Anonymous JSON 401; endpoint POST-only; missing, empty, whitespace, non-string, malformed, oversized, and injected fields rejected safely.
- CSRF-required POST and successful enforced-CSRF request.
- Owner context contains only own vehicle and upcoming appointment summaries; Technician context contains only assigned appointment summaries; Administrator receives only bounded safe operational counts. JSON primitives only; no notes, passwords, secrets, tokens, cookies, or permission internals.
- Central prompt includes CARVIX-specific security instructions. Unavailable provider and provider exception produce safe structured errors; fake provider can produce a controlled response; no network calls.
- Empty explicit registry rejects unknown/unregistered call requests; no booking, status change, inventory change, or maintenance record side effect.
- Chat template exposes namespaced endpoint, CSRF token, semantic controls, and loaded JavaScript; client avoids unsafe HTML rendering.
- Run exact focused Plan 014 tests, relevant `ai_agent`/authentication tests, full PostgreSQL suite, Django check, migration check, whitespace check, migration inspection, and complete diff/scope review.

## Migration and Environment Impact

No models or migrations, dependencies, credentials, environment variables, or persistent database changes are expected. Existing PostgreSQL configuration is retained. Provider integration and any necessary credential configuration are deferred. Rollback is removal of isolated Chat/application-boundary files and URL inclusion.

## Open Questions

None blocking for the approved foundation scope. Live provider credentials are not needed to implement or test the adapter boundary.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-27

## Implementation Report

- Summary: Implemented the authenticated AI foundation and isolated asynchronous Chat UI. The production provider remains unavailable by default, and no maintenance, Slot, booking, cancellation, or other business tool is registered.
- Files created: `.agents/plans/014-ai-agent-foundation-chat.md`; `apps/ai_agent/agent.py`; `apps/ai_agent/context.py`; `apps/ai_agent/prompts.py`; `apps/ai_agent/provider.py`; `apps/ai_agent/tools.py`; `apps/ai_agent/urls.py`; `templates/ai_agent/chat.html`; `static/js/agent_chat.js`.
- Files modified: `apps/ai_agent/tests.py`; `apps/ai_agent/views.py`; `config/urls.py`.
- Chat page and endpoint: Authenticated page is namespaced at `ai_agent:chat` (`/ai/chat/`). Authenticated JSON endpoint is `ai_agent:chat-message` (`/ai/chat/message/`), POST-only, and protected by Django CSRF middleware. Anonymous page requests redirect to login; anonymous JSON requests receive HTTP 401 with the stable response shape.
- Request and response contracts: Accept JSON with only a string `message`, trimmed for handling, required nonblank, and limited to 4,000 characters. Identity, role, prompt, tools, context, and credentials supplied by a client are rejected. All endpoint JSON results contain `success`, `code`, `message`, `data`, and `errors`. Input failures use field-specific safe errors; provider unavailable/error map to safe 503/502 responses.
- Safe context: Provider receives JSON-native values only. OWNER receives username/role, up to 20 own Vehicle summaries, and up to 20 own upcoming Appointment summaries; TECHNICIAN receives username/role and up to 20 active assigned Appointment summaries, or an empty list if no TechnicianProfile exists; ADMINISTRATOR receives username/role and aggregate Appointment counts by status only. Notes, unrelated records, credentials, permissions, staff/superuser flags, QuerySets, and Model instances are excluded. Appointment times are ISO-formatted.
- System prompt: Centralized CARVIX prompt limits assistance to supplied context and registered tools, prevents invented records/identifiers and raw SQL, respects domain roles, requests focused clarification, and forbids unverified action-success claims.
- Provider boundary: Added a typed response boundary and `UnavailableProvider`; no approved SDK, credentials, environment variable, dependency, or network call is present. Provider exceptions are converted to sanitized stable failures. Fake-provider tests exercise the end-to-end response path. Live provider integration and live API verification are deferred.
- Tool registry: Explicit production mapping is empty. Dispatch accepts only a named callable in the registry, validates argument/result structure, and rejects unknown or malformed requests with safe structured failures; no arbitrary imports, reflection, evaluation, or business side effects occur. No Appointment booking/status change, inventory change, or MaintenanceRecord creation occurs. No AgentActionLog is fabricated for a rejected unregistered call. The existing Plan 013 model and sanitizer/schema/migration are unchanged; no actual registered production tool executes in this foundation, so execution logging is not invoked.
- Authentication and frontend: The page is available to OWNER, TECHNICIAN, and ADMINISTRATOR based on domain role, independent of Django staff/superuser flags. JavaScript uses fetch with same-origin credentials and the rendered CSRF token, disables duplicate submission, announces pending and result states, and renders all untrusted messages with text nodes; it does not use `innerHTML`.
- Tests executed (PostgreSQL): focused Plan 014 `AiAgentContextTests` and `AiAgentChatTests`: 17/17 passed. Relevant `apps.ai_agent.tests` and `apps.authentication.tests`: 97/97 passed. Complete suite `.venv/bin/python manage.py test -v 1`: 261/261 passed. The first focused run exposed three test assertion defects (substring ID comparison and an incorrect expected HTTP status); tests were corrected without changing production behavior, and the focused rerun passed.
- Validation: `.venv/bin/python manage.py check` passed. `.venv/bin/python manage.py makemigrations --check` reported no changes. `git diff --check` passed. `pg_isready` reported PostgreSQL accepting connections.
- Migration/environment changes: None. Inspection confirms only the pre-existing `apps/ai_agent/migrations/0001_initial.py` and `__init__.py`; no Model, Migration, dependency, credential, environment variable, or persistent database schema changes were made.
- Security checks: All three domain roles are covered; JSON identity/prompt/tool/context/credential injection is rejected; owner and technician data queries are scoped before serialization; administrator context contains aggregates only; provider exceptions do not expose internal text; CSRF rejection and successful token round trip are tested; unsupported tool requests are rejected before dispatch; page JavaScript uses text-only rendering.
- Parallel scope: Only the approved plan, AI app files, AI template/JavaScript, and `config/urls.py` changed. No Plan 015, README, docs, base template, shared CSS, business workflow, Demo Seed Data, AgentActionLog model, or migration was changed.
- Deferred scope and remaining risks: Real provider SDK/credentials/live requests and all business tools (maintenance, Slot, booking) are deferred. The app returns a safe provider-unavailable response until an approved provider integration is added. No known in-scope validation failure remains.
- Deviations from plan: None.
