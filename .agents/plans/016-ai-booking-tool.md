# Plan: AI Appointment Booking Tool

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/ai-booking-tool
- Created: 2026-09-28
- Last updated: 2026-09-28

## Objective

Register `book_maintenance_appointment` as the first side-effecting production AI tool. Execute it only through the central allowlisted dispatcher, bind identity to the authenticated server-owned actor, reuse the existing manual appointment booking service, return stable structured results, contain handler failures, and create one sanitized AgentActionLog for each registered execution attempt.

## Requirements Covered

**Explicit SRS requirements** (`docs/CARVIX_SRS_Group6.docx`, approved Version 1.0):

- FR-25: require explicit confirmation; absent or false confirmation causes no booking.
- FR-26: book only through the registered booking tool and validate identity, ownership, service, slot, capacity, and duplication.
- FR-27–29: bind execution to authenticated `request.user`, validate arguments, and enforce role/object permissions inside the tool.
- FR-30: booking is atomic and failure leaves no partial booking data.
- FR-31: create an AgentActionLog for every execution attempt.
- FR-32: return structured success/failure results.
- FR-33: assistant claims success only when backend confirms it.
- FR-34: fail safely when provider/tool execution fails.
- FR-14 and FR-35 as applicable: reject unavailable/full/expired/duplicate slots and preserve authorized audit inspection.
- SRS §6.2 identifies the Appointment `booked_by_agent` field. The service contract uses a trusted server-owned keyword-only `booked_by_agent=False` default: manual callers remain unchanged, while the AI handler explicitly supplies `True`.

**Approved architecture and implementation decisions:**

- Register only `book_maintenance_appointment`; do not register Plan 017 tools.
- Accept exactly `vehicle_id`, `service_type_id`, `slot_id`, and `confirmation`; actor is injected by the server.
- Require exact boolean `True` before invoking the booking service.
- Use the AgentActionLog `SUCCESS`/`FAILURE` vocabulary and nonnegative `duration_ms` established in Plan 013.
- Audit registered-name requests that reach dispatch, including malformed arguments, permission/confirmation/domain failures, unexpected handler errors, and malformed handler results. Unknown names remain unregistered and are not logged, consistent with Plan 014.
- A successful registered side effect and its SUCCESS AgentActionLog must commit atomically. If success auditing fails, roll back the side effect and return sanitized `internal_error`; do not retry the audit write.

## Current-State Analysis

- Baseline is clean branch `feature/ai-booking-tool` at `767630064621d0bc4f720aaea386a76d315c793a`, derived directly from merged Plan 015/main. No Plan 017 local files or changes are present.
- `apps/appointments/services.py::book_appointment(*, actor, vehicle_id, service_type_id, slot_id, booked_by_agent=False)` is the booking authority. It requires an authenticated OWNER, resolves the Vehicle with `owner=actor`, resolves ServiceType and Slot server-side, locks the Slot with `select_for_update()` in `transaction.atomic()`, rechecks active/future state, capacity, and active duplicates, and creates a PENDING Appointment with no technician. The default keeps manual callers at `booked_by_agent=False`; AI passes trusted `True`, persisted as part of that same Appointment creation. It translates the known duplicate constraint conflict after rollback. Its safe domain exception is `AppointmentBookingError` with stable `code` values.
- The manual Owner booking view calls the service with `request.user` and only the selected Vehicle, ServiceType, and Slot IDs; it does not pass the attribution flag. The existing service test asserts manual default `False`, and existing PostgreSQL transaction/concurrency tests call the same default contract.
- The service accepts no `booked_by_agent` value from model/client arguments; only the server-side keyword-only parameter controls attribution. It accepts no notes, appointment state, capacity, or client identity. Its existing `_selection_id` allows positive integers and ASCII decimal-free integer strings and rejects booleans and malformed/nonpositive values.
- `apps/ai_agent/tools.py` currently has an empty explicit registry. Its dispatcher checks names, callable handlers, dict arguments, and a partial structured result shape, but currently lets handler exceptions escape and does not audit.
- `apps/ai_agent/agent.py::respond_to_message` passes the authenticated `user` as `actor` to the dispatcher. Provider tool calls are dicts with exactly `name` and `arguments`. For a tool result it exposes backend success/code/message; failures are not turned into assistant success claims.
- `AgentActionLog` in Plan 013 requires a User, tool name, JSON-object arguments/result, `SUCCESS` or `FAILURE`, nonnegative integer `duration_ms`, and server-created timestamp. `save()` recursively sanitizes both payloads and enforces status/result consistency. Unsupported values raise ValidationError.
- Although the sanitizer accepts an empty JSON object, `AgentActionLog.arguments` is a `JSONField(blank=False)`. `full_clean()` therefore rejects `{}` with exact error `{'arguments': ['This field cannot be blank.']}`. `_write_audit()` passed the unchanged sanitized `{}` into `objects.create()`; model `save()` called `full_clean()`, the audit insert failed, and the dispatcher returned `internal_error` instead of the handler's `validation_error`. This is a Django field-validation constraint, not a sanitizer or database-schema constraint.
- Plan 014 explicitly leaves unknown/unregistered requests without a fabricated AgentActionLog. Its LOW review finding requires registered handler exceptions to be safely contained at the central boundary.
- The SRS requires AI-assisted booking and server-owned confirmation but does not define a handler exception wire contract; stable failure codes/messages and strict dispatcher validation are implementation decisions.
- PostgreSQL was unavailable during initial implementation review, so database validation was gated at that point. The final PostgreSQL validation results are recorded in the Implementation Report.
- No Model or Migration change is required. Existing migrations are limited to the committed app migrations; Plan 017 files are absent.

## Tool Contract and Responsibilities

### Public input

`book_maintenance_appointment` accepts an argument object with exactly:

- `vehicle_id`: required positive integer; positive ASCII decimal-free integer strings follow the booking-service convention.
- `service_type_id`: same identifier rules.
- `slot_id`: same identifier rules.
- `confirmation`: required actual boolean and exactly `true` to proceed.

Reject unknown fields, including `user_id`, `owner_id`, `role`, `is_staff`, `is_superuser`, `booked_by_agent`, `appointment_id`, `status`, `capacity`, notes, and arbitrary context. Booleans do not qualify as integer IDs. Validate before calling the booking service.

### Identity and authorization

The dispatcher supplies `actor` from `request.user` through the Plan 014 agent call. The model/provider never supplies actor identity. Missing or anonymous actors fail safely. The tool requires the domain OWNER role regardless of Django staff/superuser flags. It invokes the existing service with that actor; vehicle ownership is filtered and rechecked there. Foreign/missing vehicles return safe results without identifying another owner's data.

### Confirmation

Only `confirmation is True` can call the booking service. Missing, false, or non-boolean confirmation returns a failure and makes no business write or capacity reservation.

### Structured results

All dispatcher/handler results have exactly `success`, `code`, `message`, `data`, and `errors`. `success` is boolean; `code` and `message` are strings; `data` and `errors` are objects or null. Data contains only a persisted booking summary (`appointment_id`, `vehicle_id`, `service_type_id`, `slot_id`, `status`, and safely useful Slot start/end values). No Model, QuerySet, notes, email, SQL, exception text, or traceback is returned.

Expected public mappings: malformed/unknown fields and IDs -> `validation_error`; role/ownership -> `permission_denied`; missing ServiceType -> `not_found`; missing/inactive/expired/full Slot and booking conflict -> `slot_unavailable`; active duplicate -> `duplicate_booking`; missing/false confirmation -> `confirmation_required`; unexpected handler/audit failure or malformed result -> `internal_error` / `invalid_tool_result` as applicable. Messages are fixed safe strings and do not expose raw domain exception text.

### Registry and dispatcher

- Use one explicit mapping for `book_maintenance_appointment` only; no aliases, imports, reflection, eval, or exec.
- Resolve only registered callables. Reject unknown tools without logging them, in accordance with Plan 014.
- A registered-name request reaching dispatch is one audit attempt, including invalid argument shape. Do not log inside the booking handler.
- The dispatcher owns actor injection, monotonic timing, handler exception containment, strict result validation and JSON serializability, sanitization, and exactly-once AgentActionLog creation. Provider calls remain outside its transaction boundary.
- Handler exceptions never escape to the Chat endpoint. Expected domain outcomes are converted by the handler; unexpected exceptions become a safe failure. Malformed/non-serializable handler results become a safe failure.
- Execute a registered Handler and validate its result inside an outer `transaction.atomic()`. The booking service retains its own nested atomic block and all booking rules. For a valid success, write the SUCCESS audit inside the outer block and return success only after both commit. If success audit persistence or the coordinated commit fails, roll back the booking and return sanitized `internal_error` without retrying the audit.
- For a structured failure, malformed result, or unexpected Handler exception, roll back the Handler transaction first, then write one FAILURE audit in a clean transaction. Preserve structured expected failures; map unexpected exceptions to sanitized `internal_error` and malformed results to `invalid_tool_result`. Audit failures are never retried.
- Store sanitized arguments/result using Plan 013 `sanitize_payload`; preserve nested credential redaction. Duration is integer milliseconds from `time.monotonic_ns()`, clamped nonnegative; timestamp comes from the model.
- For a supplied empty argument object only, store the deterministic non-empty JSON envelope `{"_supplied_arguments": {}}`. This preserves the fact that the caller supplied `{}` while satisfying the existing `JSONField(blank=False)` model validation. Do not skip audit or alter the Model/Migration.
- If actor is missing/unsaved, audit persistence is impossible; return a safe failure without claiming success. If SUCCESS audit persistence fails, the outer transaction rolls back the business side effect. Do not retry an audit operation whose commit status may be uncertain.

### Booking service and transaction ownership

The handler validates the AI schema and confirmation, checks the OWNER role, then calls the existing `book_appointment` service with `booked_by_agent=True` as a trusted server-owned keyword. Manual callers omit that argument and retain the `False` default. The service alone owns lookup, ownership enforcement, nested transaction, Slot row lock, capacity/duplicate checks, Appointment fields, and persistence. The AI flag is written during Appointment creation inside the existing atomic booking operation. The dispatcher’s outer registered-execution transaction coordinates that nested booking transaction with the success AgentActionLog. The model/client/provider/Chat payload cannot set the attribution value. Do not duplicate booking rules, perform a post-creation update, or use compensating cleanup. Manual booking behavior is unchanged.

### Chat boundary

Plan 014 remains the only provider/Chat integration. `respond_to_message` passes its authenticated User to the registered dispatcher. Fake-provider coverage verifies that a registered request can book only with confirmation, returns backend truth, contains failures, and makes no external network call. No live provider SDK is added.

## Proposed Changes

- `.agents/plans/016-ai-booking-tool.md`: this approved plan and final implementation report.
- `apps/appointments/services.py` (modify): add the trusted keyword-only `booked_by_agent=False` parameter and persist its value during existing Appointment creation.
- `apps/ai_agent/booking_tool.py` (create): strict input/confirmation/role validation, service invocation, safe outcome mapping, minimum persisted summary.
- `apps/ai_agent/tools.py` (modify): register the single production tool; contain exceptions; strictly validate/sanitize results and record one audit attempt.
- `apps/ai_agent/test_booking_tool.py` (create): focused adapter, registry, audit, exception, and fake-provider integration tests.
- `apps/ai_agent/tests.py` (modify): update the Plan 014 assertion that the registry is empty, since Plan 016 intentionally registers one tool. No existing behavior tests are weakened.
- `apps/appointments/tests.py`: existing manual booking default test already proves the omitted argument persists `False`; keep it and existing transaction/concurrency coverage unchanged.

No Plan 017 path, Model, Migration, appointment model, template, frontend, README, docs, dependency, environment file, or authoritative SRS change is planned.

## Risks and Problems

- The dispatcher must contain failures only after the booking service's transaction has exited; its current implementation propagates domain errors after rollback, allowing the dispatcher to audit safely.
- Logging a FAILURE after a handler exception must not create a second business write or duplicate log. One dispatcher-owned audit call is the only audit path.
- AgentActionLog requires a persisted authenticated User; anonymous/unavailable actor cannot produce a valid audit row. The Chat endpoint authenticates the request before agent execution.
- If the audit database itself is unavailable, exactly-once persistence cannot be guaranteed; the dispatcher must return safe failure and not leak database details.
- The service contract must keep AI attribution server-owned. A keyword-only `False` default preserves every manual caller; the AI adapter passes `True` explicitly. Never accept the flag from tool arguments or add a post-creation update.
- Provider output remains untrusted. Only the registry mapping can dispatch code, and the tool independently validates its arguments and permissions.
- PostgreSQL row locking and concurrency are transaction-critical; retain the existing PostgreSQL transaction/concurrency coverage for future service changes. No SQLite substitution is allowed for those checks.

## Alternatives Considered

### Option A — Strict AI adapter and central audited dispatcher (Recommended)

Add a thin tool adapter around the already validated manual booking service, and make the central dispatcher own exception containment, result validation, and audit. This keeps authorization and transaction logic in the existing domain boundary while closing the Plan 014 exception finding.

### Option B — Duplicate booking rules in the AI tool or create an AI-specific transaction

This could tailor the result and attribution behavior to AI, but duplicates ownership/capacity/locking rules and risks concurrency regressions and partial writes. It conflicts with the SRS requirement to use validated backend tools and with the explicit project decision to reuse the service.

## Recommended Approach

Use Option A. It is the smallest change that meets FR-25–33 and the approved project architecture. Keep one source of booking business rules and one dispatcher-owned audit record per registered attempt.

## Implementation Steps

1. Implement the thin strict booking adapter over `book_appointment`.
2. Register only that adapter and implement dispatcher validation, exception containment, duration, sanitization, and exactly-once audit.
3. Add focused tests and update the existing registry-empty assertion to match the approved registry.
4. Run the required checks in the requested order only when PostgreSQL is available; otherwise complete static review, leave this Plan APPROVED, and do not stage/commit/push.
5. Review full diff and scope; finalize this Plan only after every required gate passes.

## Test Plan

- Input schema: exact required fields; missing/extra/client identity fields rejected; bool, zero, negative, fractional, malformed IDs rejected; supported positive integer strings follow the existing service convention; confirmation requires exact bool `True`.
- Authentication/authorization: missing/anonymous actor, non-Owner Technician/Administrator, staff/superuser role mismatch, own Vehicle, foreign/missing Vehicle, no private detail leakage.
- Booking: confirmed valid booking creates one PENDING Appointment linked to selected Vehicle/ServiceType/Slot; service reuse is patched/observed; service owns slot locking/capacity/duplicate behavior; existing failure codes map safely; no booking without confirmation or after any failure.
- Attribution: manual service caller omits the new keyword and persists `False`; AI adapter passes `True` and persists it on initial creation; client-supplied `booked_by_agent` is rejected; failures and `confirmation=false` create no Appointment; exactly one Appointment creation save occurs with no second update. Preserve the existing manual transaction and PostgreSQL concurrency tests.
- Result contract: all five exact top-level keys and value shapes for success/failure; minimal JSON-native data; no Model/QuerySet/notes/secrets/raw exception/traceback; malformed and nonserializable handler result safely rejected.
- Registry: exactly one public booking name, no aliases/read-tool names, unknown tool rejected, correct server actor injected, invalid callable/duplicate safeguards if exposed by the registry API.
- Audit: one AgentActionLog for success, empty/missing/invalid arguments, permission, confirmation, expected domain failure, unexpected exception, and malformed result; empty input is stored as `{"_supplied_arguments": {}}` with the original structured validation result; correct actor/tool/status; sanitized nested payloads; nonnegative millisecond duration; server timestamp; no duplicate/fake-success log. A successful booking and its success audit commit atomically. A failed success-audit write rolls back the booking and is not retried.
- Exception containment: handler RuntimeError and secret-bearing text become safe structured `internal_error`; Chat endpoint does not raise 500 and assistant reports failure. The Handler transaction rolls back before a clean failure-audit transaction begins.
- Fake-provider Chat: registered tool request, successful truthful result, failure/exception truthful result, missing confirmation no write, forged identity rejected, no network call.
- Regression: ai_agent, appointments, vehicles, authentication, AgentActionLog, seed/demo tests where appropriate, then complete PostgreSQL suite.
- Validation gates: `pg_isready`, Django check, `makemigrations --check`, focused tests, relevant tests, full suite, `git diff --check`, migration/scope inspection, and full diff review.

## Migration and Environment Impact

`MIGRATIONS_EXPECTED: NO`. No models, migrations, dependencies, environment variables, or persistent schema changes. Rollback removes the booking adapter/registration/tests and restores the previous dispatcher/registry behavior; the manual booking service and workflow remain intact.

## Open Questions

None blocking. Manual booking uses the service's default `booked_by_agent=False`; AI booking supplies trusted server-owned `True` during the same Appointment creation transaction. The outer dispatcher transaction includes the success audit and controls final commit.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-28

## Implementation Report

- Summary: Implemented the confirmed `book_maintenance_appointment` tool through the existing manual booking service, with strict input and OWNER authorization checks, server-owned attribution, central structured-result validation, exception containment, and transactional audit coordination. The deferred Plan 014 LOW exception-containment finding and the independent PR #22 MEDIUM finding are closed. No duplicate booking logic, compensating delete, or post-creation Appointment update was added.
- Files created: `.agents/plans/016-ai-booking-tool.md`; `apps/ai_agent/booking_tool.py`; `apps/ai_agent/test_booking_tool.py`.
- Files modified: `apps/appointments/services.py`; `apps/ai_agent/tools.py`; `apps/ai_agent/tests.py`. Existing manual booking tests and transaction/concurrency coverage were preserved.
- Tool and input contract: The sole public production Tool is `book_maintenance_appointment`. Its exact argument keys are `vehicle_id`, `service_type_id`, `slot_id`, and `confirmation`. IDs must be positive integers or positive ASCII decimal integer strings within the supported integer range; booleans, zero, negative, fractional, malformed, and out-of-range values are rejected. Unknown fields—including `booked_by_agent`, identity, role, status, and capacity fields—are rejected. `confirmation` must be the actual boolean `true`.
- Identity and authorization: The authenticated actor is injected server-side from `request.user`; neither client arguments nor provider output can select the actor. The tool requires the OWNER role, and the existing service scopes and rechecks Vehicle ownership. Staff/superuser flags do not grant Owner authorization.
- Booking and attribution: The AI adapter reuses `apps.appointments.services.book_appointment`. Manual callers omit the new keyword and persist `booked_by_agent=False`; the AI handler explicitly passes trusted `booked_by_agent=True`. The value is persisted during initial Appointment creation inside the service's atomic operation. The booking service remains the authority for locking, capacity, duplicate checks, IntegrityError translation, and rollback. The dispatcher adds an outer transaction so booking and the success audit commit together; the nested service transaction remains intact.
- Structured results and registry: Every result has exactly `success`, `code`, `message`, `data`, and `errors`, with validated value types and sanitized JSON payloads. The production registry contains only `book_maintenance_appointment`; explicit isolated test registries remain executable, while unknown names remain rejected before handler execution.
- Exceptions and audit: Registered-handler exceptions are contained centrally; malformed handler results become safe `invalid_tool_result` failures. Success auditing runs in the same outer transaction as Handler effects; a success-audit failure rolls back the Appointment and is not retried. Structured failures, unexpected exceptions, and malformed results roll back Handler effects before one FAILURE audit attempt in a clean transaction. Empty arguments retain `validation_error` and are stored as `{"_supplied_arguments": {}}`. Arguments and results are recursively sanitized; duration is server-generated and nonnegative. Provider generation remains outside database transactions.
- Tests and PostgreSQL validation: Focused Plan 016 tests passed 26/26; relevant AI Agent, Appointments, Authentication, and Vehicles tests passed 242/242; Demo Seed Data tests passed 4/4; and the complete PostgreSQL suite passed 287/287. The provided PostgreSQL validation also confirmed booking/audit atomicity, rollback after post-booking audit failure, no remaining Appointment or audit row, unconsumed Slot capacity, and a successful single retry. The supplied results were manually verified; these tests were not rerun in this turn.
- Final checks: `python manage.py check` passed. `python manage.py makemigrations --check` reported no changes detected. `git diff --check` passed. No Model or Migration changed.
- Scope and migration impact: No Model or Migration changes; `MIGRATIONS_EXPECTED: NO`. No Plan 017 or read-tool files changed. Live provider integration and read-tool registration remain deferred. No dependency, environment, template, JavaScript, documentation, or AgentActionLog schema changes were introduced.
- Final diff review: Reviewed the correction for actor binding, strict identifiers and confirmation, service transaction ownership, attribution persistence, exception/result containment, audit ordering, sanitization, rollback, allowlisting, and scope. No BLOCKER, HIGH, or MEDIUM issue remains.
- Git actions: This Plan remains on `feature/ai-booking-tool`. It is finalized as IMPLEMENTED after the supplied PostgreSQL validation results and the final checks above. Commit and push are performed as the final authorized steps for this task.
- Remaining deferred work: Live provider integration and Plan 017 read-tool registration.
- Deviations from plan: None.

## Independent Review Correction (Validated)

- The independent PR #22 review identified a MEDIUM finding: the booking service could commit an Appointment before a later success-audit failure caused the dispatcher to return `internal_error`.
- Corrected policy: successful registered Handler execution and its SUCCESS AgentActionLog are coordinated in the dispatcher's outer transaction. The existing booking service remains the sole booking authority and runs its existing nested atomic operation. A failed success-audit write rolls back the Appointment; no compensating delete, retry, second Appointment update, or duplicated booking logic is used.
- Structured failures, malformed Handler results, and unexpected Handler exceptions roll back the Handler transaction before one FAILURE audit attempt in a clean transaction. The provider call remains outside this transaction.
- Added regression coverage forces the success audit write to fail after observing that the normal booking Handler created an Appointment, then asserts rollback, no remaining Appointment or audit row, unconsumed capacity, and a successful single retry. Additional coverage checks side-effect rollback for unexpected exceptions and malformed results, plus no retry when failure auditing fails.
- PostgreSQL validation passed: focused Plan 016 tests 26/26; relevant AI Agent, Appointments, Authentication, and Vehicles tests 242/242; Demo Seed Data tests 4/4; complete PostgreSQL suite 287/287. Django check passed, `makemigrations --check` found no changes, and `git diff --check` passed.
- Model/Migration inspection found no changes. No local Plan 017 or read-Tool files changed. Provider calls remain outside database transactions.
- The original transaction-ordering defect is resolved: `internal_error` after a failed success-audit write does not accompany a retained booking. No compensating delete or audit retry is used.
