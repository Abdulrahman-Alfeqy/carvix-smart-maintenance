# Plan 018: End-to-End AI Tool Integration

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: `feature/ai-tool-integration`
- Created: 2026-09-28
- Last updated: 2026-09-28

## Objective

Register the three approved CARVIX Tools in the audited production Registry and complete a bounded request-local Agent loop that validates one Tool request at a time, injects the authenticated actor, executes through the central dispatcher, returns a sanitized structured observation to the Provider, and returns a final response that cannot override backend failure truth. Validate the complete flow with Fake Providers only. Do not add a live Provider SDK or credentials.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`, approved Version 1.0.

- FR-21–24: authenticated conversational assistance, safe context, maintenance checks, and eligible slot discovery.
- FR-25–30: explicit booking confirmation, registered booking Tool, server-bound identity, strict validation/authorization, and atomic booking.
- FR-31–34: one audit record per registered Tool attempt, structured results, backend-confirmed success only, and safe Provider failure.
- NFR-S01–S07, NFR-R01–R03, and NFR-M01–M02: authentication, CSRF-preserving endpoint boundary, ownership and role enforcement, no raw SQL or identity from Provider arguments, sanitized failures, transactional writes, auditability, and application separation.
- SRS §§4–5 and 8.1–8.10: the three domain roles, least context, explicit allowlist, Tool schemas, structured observations returned to the Provider, bounded reasoning/action/observation loop, and a final response based on verified results.
- SRS UJ-05–UJ-09: maintenance, slot, confirmed booking, denied access, and unavailable-slot behavior.

## Current-State Analysis

- Baseline is clean `feature/ai-tool-integration` at `26cde397b691c39387909da6cc34706e405f89fa`. Plans 016 and 017 and all three handlers are present. The branch currently points at `origin/main`; it has no feature-branch upstream yet.
- Plan 013 supplies `AgentActionLog` and recursive `sanitize_payload`; Plan 016 supplies `book_maintenance_appointment` and the central audited dispatcher; Plan 017 supplies independently implemented `check_required_maintenance` and `list_available_service_slots` handlers. Plans 016 and 017 report no Model or Migration changes.
- `apps/ai_agent/tools.py::TOOL_REGISTRY` currently explicitly contains only `book_maintenance_appointment`. `_register_tool` rejects silent replacement. `execute_tool_request(name, arguments, *, actor, registry=None)` validates the exact five-field result, sanitizes it, catches handler exceptions, and coordinates each registered execution with one AgentActionLog. A successful Handler effect and SUCCESS audit commit together; failures roll back before one FAILURE audit attempt. Unknown names do not execute or get logged.
- `booking_tool.book_maintenance_appointment(*, actor, arguments)` accepts exactly `vehicle_id`, `service_type_id`, `slot_id`, and exact boolean `confirmation=True`; requires an authenticated Owner; reuses the existing booking service with server-owned `booked_by_agent=True`. Manual booking retains `False`.
- `maintenance_tool.check_required_maintenance(*, actor, arguments)` accepts exactly `vehicle_id`, requires authenticated OWNER and an owner-scoped Vehicle, and reuses `get_vehicle_maintenance_overview`. `slot_tool.list_available_service_slots(*, actor, arguments)` accepts `service_type_id` and optionally Plan 017's strict `preferred_date`; it requires an authenticated OWNER, TECHNICIAN, or ADMINISTRATOR and reuses `get_available_service_slots`. Neither Handler writes. The date is validated but does not filter because date/time matching is undefined; slots are global because no ServiceType-to-Slot relation exists.
- `ProviderReply` contains `text` and optional `tool_call` with expected keys `name` and `arguments`. `Provider.generate(*, message, system_prompt, context)` is the only current contract; `UnavailableProvider` makes no network call. No live Provider implementation exists.
- `respond_to_message(*, user, message)` currently makes one Provider call. A returned Tool request is dispatched once and the Agent immediately returns the Handler result; there is no observation round trip or final Provider generation after a Tool.
- Current Chat output is a `ChatResult` serialized by the existing view as `success`, `code`, `message`, `data`, and `errors`. Direct Provider text is placed in `data.assistant_message`; the endpoint and its authentication/CSRF behavior remain unchanged.
- The authoritative SRS confirms three named Tools and requires structured observations to return to the Provider before its final response. It also requires request.user identity, server validation, audited execution, and backend truth. The accepted Plans resolve the SRS's existing preferred-date and global-slot constraints; this plan preserves those decisions.
- No genuine requirements or architecture blocker exists. `MIGRATIONS_EXPECTED: NO`.

## Registered Tool Contracts and Internal Schemas

The only production names, with no aliases, are:

1. `check_required_maintenance`
   - JSON object, required `vehicle_id` (positive integer identifier; existing Handler also accepts positive ASCII decimal strings).
   - Reject `user_id`, `owner_id`, `role`, arbitrary context, and every unknown property.
   - Owner-only; the Vehicle must be owned by the injected actor.
2. `list_available_service_slots`
   - JSON object, required `service_type_id` (positive integer identifier; existing Handler also accepts positive ASCII decimal strings); optional `preferred_date` only as supported by Plan 017 (`YYYY-MM-DD`).
   - Reject identity, capacity, active-state, arbitrary date ranges, and every unknown property.
   - Allow the three approved domain roles. Preserve Plan 017 global eligibility and its validated-but-not-filtered preferred date.
3. `book_maintenance_appointment`
   - JSON object, required `vehicle_id`, `service_type_id`, `slot_id` (positive integer identifiers; existing Handler also accepts positive ASCII decimal strings), and `confirmation` (actual boolean).
   - Reject `user_id`, `owner_id`, `role`, `booked_by_agent`, status, capacity, and every unknown property.
   - Owner-only; only exact `confirmation=true` can reach the existing booking service.

Create `apps/ai_agent/tool_schemas.py` with one explicit, JSON-native internal schema per exact name, `additionalProperties: false`, required fields, property types, safe descriptions, and no secrets or server-owned identity. The schema mapping keys must match the production Registry names exactly. Handler validation remains authoritative for value ranges and domain rules.

## Agent Loop and Provider Boundary

1. Build the existing safe role-scoped context from the authenticated request user.
2. Call the current Provider contract outside every database transaction, supplying the safe context and the trusted internal schemas.
3. Accept either one direct nonblank final text response or exactly one well-formed `{name, arguments}` Tool request. Reject malformed replies, extra request keys, multiple Tool requests, blank final text, and unknown names without executing arbitrary code.
4. For a registered request, use the central dispatcher only. The dispatcher receives `actor=user` from the server; Provider arguments cannot select identity or role.
5. Append one observation to the Provider context and call the Provider again. Continue for at most three Tool rounds. On a normal completion, return the final Provider text in the existing structured Chat response shape, together with safe Tool results.
6. A generation that requests a fourth Tool, makes a repeated request, or requests another Tool after a Tool failure terminates safely without dispatching the prohibited request. No Tool loop is unbounded.

To preserve the existing `Provider.generate(message, system_prompt, context)` interface and current Fake Providers, deliver Tool schemas and observations as reserved server-created entries in the JSON-native context (`tool_schemas` and `tool_observations`); do not add an SDK or a new Provider method. Existing application context remains available in its current top-level role-scoped shape. Update the system prompt to tell the Provider to treat observations as backend truth and never turn a failed observation into success.

## Observation and Chat Result Contracts

Each Provider observation is a JSON-native object with exactly:

- `tool_name`
- `success`
- `code`
- `message`
- `data` (sanitized object or null)
- `errors` (sanitized object or null)

The observation is built from the centrally validated five-field Handler result, sanitized recursively, and contains no actor, Model, QuerySet, traceback, exception repr, SQL, secret, or database detail. Do not log the observation as another Tool execution.

Keep the existing HTTP ChatResult five-field contract and `data.assistant_message`. Include only safe structured Tool results in data. If any executed Tool result has `success=false`, the final Chat response preserves its backend failure code/message/errors and does not display Provider text that might contradict it. Provider text cannot turn failure into success. If Provider generation fails after a successful side effect, return the actual successful backend result in a safe fallback response; never suggest the booking failed or automatically retry it.

## Limits, Repeated Calls, and Failure Handling

- `MAX_TOOL_ROUNDS = 3` dispatched Tool requests per Chat turn.
- Detect repeated calls by canonical JSON identity of the Tool name and arguments; do not dispatch an identical call twice in the same turn. Invalid/non-JSON requests are rejected before fingerprinting or Handler dispatch.
- Once `book_maintenance_appointment` succeeds, no further booking request in that turn may dispatch, even with different arguments. Preserve the first actual booking result and state safely that no additional booking was created.
- Once a Tool fails, do not dispatch a subsequent Tool automatically in that turn. Return the failure observation to the Provider for a final response, then preserve backend failure truth in the Chat response.
- Multiple Tool requests, malformed Tool requests/arguments, unknown Tools, repeated calls, limit overflow, provider exceptions, malformed response objects, blank Provider text, and invalid Handler results all terminate as safe structured outcomes. Do not expose stack traces, secrets, or exception details.
- Unknown Tool names remain unregistered and do not create a fabricated AgentActionLog. Each registered dispatch attempt, including invalid arguments rejected by its Handler, uses exactly one central audit attempt. Agent and Handler must not duplicate audits.

## Authentication, Authorization, Auditing, and Transactions

- Only authenticated request users with one of the exactly three domain roles may use the current Chat endpoint. Preserve `request.user` as the only identity source; `is_staff` and `is_superuser` do not substitute for domain roles.
- Reuse the existing per-Handler authorization. Maintenance lookup remains Owner-only and owner-scoped; slot listing preserves Plan 017's role set; booking remains Owner-only and the booking service rechecks ownership, availability, capacity, and duplicate booking.
- Every registered Tool uses `execute_tool_request` and the existing AgentActionLog boundary. Keep result validation, recursive sanitization, monotonic duration, and safe exception handling centralized. Provider generation happens before/after dispatcher transactions and never inside them.
- Read handlers remain read-only; their one central AgentActionLog write is the required audit, not a business-data mutation. Booking and SUCCESS audit remain atomic in the existing nested/outer transaction arrangement. Success-audit failure rolls back the Appointment and is not retried.
- No Model, Migration, raw SQL, direct Provider-to-ORM path, live network call, secret, or persistent Chat model is introduced.

## Proposed Files

- `.agents/plans/018-ai-tool-integration.md`: this approved plan and final report, finalized only after every validation gate passes.
- `apps/ai_agent/tool_schemas.py`: the exact three internal JSON schemas and safe descriptions.
- `apps/ai_agent/tools.py`: explicit duplicate-safe registration of all three handlers and schema-aligned dispatch safeguards while preserving exactly-once audit and transactions.
- `apps/ai_agent/agent.py`: bounded Tool round trip, safe observations, final Provider response, duplicate/booking-repeat prevention, and backend-truth response handling.
- `apps/ai_agent/prompts.py`: observation and backend-truth guardrails.
- `apps/ai_agent/test_tool_integration.py`: Fake Provider end-to-end coverage for direct responses, all three Tools, loop bounds, repeat prevention, result round trips, errors, and no external calls.
- `apps/ai_agent/tests.py`, `apps/ai_agent/test_booking_tool.py`, and `apps/ai_agent/test_read_tools.py`: update only existing assertions that intentionally encoded the superseded one-Tool/unregistered-read-Tool Registry boundary; retain their behavioral coverage and strengthen them to assert the exact three production mappings.

These three existing test modules require a narrow expectation update because the approved integration explicitly changes the production Registry contract. No other file is expected.

## Risks and Alternatives

- A model could repeat a successful booking or reinterpret a failed observation. The bounded loop, canonical repeated-call tracking, booking-success latch, and backend-truth response policy prevent repeated side effects and false success.
- A returned Handler object could contain unsafe or non-JSON values. The central dispatcher validates and sanitizes results before audit/return; observations are sanitized again at the Provider boundary.
- Registering a read Handler without audit would violate FR-31. All three names are registered only through the existing central dispatcher; no Handler writes its own AgentActionLog.
- Provider calls while an outer transaction is open could hold locks during network latency. The Agent calls Provider only between dispatcher returns; each dispatch transaction has completed first.
- Slot schema wording might imply filtering by service/date. Preserve the already approved Plan 017 fact: service type is validated, slots remain global, and `preferred_date` is validation-only until requirements define timezone matching.
- Alternative A: use an internal schema module and context-carried observations with the existing Provider interface. This reuses the current boundary and Fake Providers without SDK changes.
- Alternative B: add Provider method parameters or a transcript abstraction now. This could model turns explicitly but expands the public Provider contract despite no live adapter and forces unrelated Provider changes. Prefer Alternative A for the bounded local integration.

## Recommended Approach

Use Alternative A. Register the existing three independently tested Handlers, keep the dispatcher as the single audit and transaction authority, carry trusted schemas/observations through the existing JSON-native Provider context, and make the Agent own only bounded orchestration and final response truth. This satisfies the SRS without adding dependencies, Models, Migrations, live network behavior, or duplicate domain logic.

## Implementation Steps

1. Create this approved Plan 018 with discovery facts, schema/loop choices, acceptance gates, and migration boundary.
2. Add explicit JSON-native Tool schemas and register the two read Handlers plus the existing booking Handler; preserve dispatcher result validation and audit coordination.
3. Implement the three-round Agent tool-observation loop, repeat guards, strict request parsing, safe final response behavior, and prompt guardrails.
4. Add Fake Provider tests for direct response, maintenance, slots, confirmed booking, failures, identity, round trip, repeat prevention, limits, sanitization, and no network calls.
5. When PostgreSQL is available, run all validation gates in the specified order, inspect Model/Migration state, perform complete diff/security review, and stop at the first genuine failure.
6. Mark this Plan IMPLEMENTED only after all required tests and validation gates pass. Otherwise leave it APPROVED and record the exact blocker and incomplete gates.
7. Only after every gate passes, stage the Plan 018 files, create exactly `feat: integrate AI tool-calling workflow`, and push with `git push -u origin feature/ai-tool-integration`.

## Test Plan

Use Fake Providers only; make no external requests.

- Direct final text: valid structured Chat success, no dispatch, no AgentActionLog.
- Schemas/Registry: exact three names, explicit callable mapping, no aliases or duplicates, exact required/optional fields, no identity or server-owned fields, unknown/extra properties rejected, schemas JSON-native. Update the legacy one-Tool Registry assertions without weakening surrounding tests.
- Maintenance flow: injected Owner, own Vehicle result observed by Provider, cross-owner failure safely observed, one audit each, no business writes.
- Slot flow: injected supported role, eligible slots and Plan 017 preferred-date behavior reflected, one audit, no booking/reservation.
- Booking flow: missing/false confirmation never books; exact true books once with `booked_by_agent=True`; one success audit; final Provider response follows backend result; no repeat booking.
- Observation: exact six safe fields, JSON round-trip, sanitized data/errors, no actor, ORM values, traceback, SQL, secrets, or duplicate audit for the Provider round trip.
- Failure paths: unknown Tool, malformed/multiple request, extra/missing/invalid arguments, wrong role, cross-owner, full/expired/duplicate slot, Handler exception, audit failure, malformed Provider response, blank response, Tool failure followed by Provider success text, repeated call, booking repeated with different arguments after success, and round limit.
- Exactly-once audit: each registered dispatch is logged once at the central boundary; Provider generations and blocked/unknown requests are not logged as executions; booking plus success audit remain atomic.
- Regression: preserve Plan 014 chat tests, Plan 016 booking/transaction tests, Plan 017 direct read-tool tests, Manual Booking, Due-Service, Slot Discovery, Authentication, AgentActionLog, Demo Seed Data, and complete PostgreSQL suite.
- Required gates, only on PostgreSQL: `pg_isready`; Django check; `makemigrations --check`; focused Plan 018 tests; all `apps.ai_agent` tests; relevant domain tests; Demo Seed Data tests; complete PostgreSQL suite; `git diff --check`; Model/Migration inspection; full diff and scope/security review.

## Migration and Environment Impact

`MIGRATIONS_EXPECTED: NO`. No Models, Migrations, dependencies, settings, environment variables, credentials, persistent schema changes, or live Provider SDK. PostgreSQL remains the sole database. No persistent Chat state is added. Rollback removes the internal schemas and orchestration/registration changes and restores the prior one-Tool Agent path; the independently tested Handlers and manual workflows remain intact.

## Open Questions

None blocking. The approved Handler contracts, role boundaries, date behavior, slot-selection semantics, and booking/audit transaction policy are supplied by Plans 016/017 and the authoritative SRS.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-28

## Definition of Done

- All three exact Tool names and internal schemas are present and explicitly registered.
- The bounded Agent loop returns sanitized observations to the Provider and obtains a final response on successful flows.
- Repeated calls, round overflow, malformed requests, and Tool failures cannot create duplicate side effects or hallucinated success.
- Every registered execution is centrally validated, sanitized, and audited exactly once; booking and SUCCESS audit remain atomic.
- All focused, AI, relevant domain, seed, complete PostgreSQL, system, migration, whitespace, Model/Migration, and final review gates pass.
- No live Provider, secret, Model, Migration, dependency, unrelated file, or unapproved scope is introduced.
- One approved-scope commit is pushed to the named branch only after all gates pass.

## Implementation Report

- **Status and decision:** `IMPLEMENTED`; Decision remains `APPROVED`. Branch: `feature/ai-tool-integration`.
- **Implementation summary:** Integrated the three approved handlers in the audited production Registry and added internal JSON-native schemas, role-filtered schema context, a bounded three-round Provider/Tool loop, sanitized observations, repeated-request and repeat-booking guards, and backend-truth response handling. Provider calls remain outside dispatcher transactions. The existing `Provider.generate(message, system_prompt, context)` interface is preserved.
- **Files created:** `.agents/plans/018-ai-tool-integration.md`; `apps/ai_agent/tool_schemas.py`; `apps/ai_agent/test_tool_integration.py`.
- **Files modified:** `apps/ai_agent/tools.py`; `apps/ai_agent/agent.py`; `apps/ai_agent/prompts.py`; `apps/ai_agent/tests.py`; `apps/ai_agent/test_booking_tool.py`; `apps/ai_agent/test_read_tools.py`. The three existing test modules retain their behavior coverage and update Registry expectations to assert the exact approved mappings. This Plan file was finalized with this report.
- **Schemas and Registry:** `TOOL_SCHEMAS` and the production `TOOL_REGISTRY` contain exactly `check_required_maintenance`, `list_available_service_slots`, and `book_maintenance_appointment`. Each schema rejects additional properties and excludes identity/server-owned fields. Registration is explicit, duplicate-safe, and checked against schema names. Each dispatch uses `execute_tool_request`; handlers are not called around the central boundary.
- **Authorization and ownership:** The Agent supplies the authenticated request user as `actor`; Provider arguments cannot supply actor identity or role. The maintenance handler is Owner-only and filters the Vehicle by that Owner. Slot discovery permits the approved Owner, Technician, and Administrator roles. Booking remains Owner-only and reuses the booking service's ownership and availability checks. Role-filtered schemas supplement, and do not replace, handler authorization.
- **Structured results and separation:** Every handler result is validated as the five-field `success`, `code`, `message`, `data`, and `errors` shape. Provider observations add only `tool_name`, are recursively sanitized, and contain exactly six fields. Maintenance and slot handlers remain read-only with respect to business data; booking remains the only business-data mutation. No direct Provider-to-ORM path was introduced.
- **Audit and rollback:** All registered executions are centrally audited once. Provider generations and blocked or unknown requests are not execution audits. Booking and its success audit remain in the existing atomic transaction boundary; failure of success-audit persistence rolls the booking back. Handler failures roll back before the central failure-audit attempt, and a possibly completed audit insert is not retried.
- **Failure isolation and false-success prevention:** Provider exceptions and malformed replies return safe structured outcomes without exception details. A failed Tool result remains authoritative over later Provider text, subsequent automatic Tool dispatch stops after failure, and a Provider failure after committed booking preserves the backend success result. The action-success guard rejects matched booking/action claims without a successful backend result, including generic completion after a mutation-intent request. Identical requests and additional bookings after a successful booking are stopped.
- **Validation:** Manually verified on PostgreSQL for this branch: Plan 018 focused tests **18/18 passed**; all AI Agent tests **90/90 passed**; relevant domain tests **222/222 passed**; Demo Seed Data tests **4/4 passed**; complete PostgreSQL suite **319/319 passed**; Django check passed; `makemigrations --check` reported no changes; `git diff --check` passed. These are the final combined validation counts; no separate historical Plan 018 count is asserted here.
- **Model and Migration verdict:** `MIGRATIONS_EXPECTED: NO`. Plan 018 introduced no Model or Migration changes.
- **Deviations:** No implementation deviation is recorded. Plan 017's existing global slot eligibility and validation-only `preferred_date` behavior are preserved.
- **Deferred scope:** No live Provider SDK or external network calls, persistent Chat model/state, new dependencies, Model, Migration, or undefined ServiceType-to-Slot/date-filtering behavior was introduced. Provider-specific schema translation remains outside this plan.
