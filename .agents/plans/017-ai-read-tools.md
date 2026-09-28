# Plan 017: AI Read-Only Tools

## Metadata

- Status: APPROVED
- Related issue: N/A
- Owner: TBD
- Reviewer: TBD
- Branch: `feature/ai-read-tools`
- Created: 2026-09-28
- Last updated: 2026-09-28

## Objective

Add two independently importable, directly testable, read-only AI tool handlers that adapt the existing maintenance due-service service and available-slot selector to the SRS structured-result contract. Each handler binds authorization to the server-supplied actor, validates arguments, returns JSON-native data, and performs no writes. Do not connect either handler to the central Tool Registry or claim end-to-end AI execution or AgentActionLog execution integration.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`.

- FR-11: calculate due/overdue maintenance from configured intervals and recorded history; result includes service, status, last service, and reason.
- FR-12: Owners can view active slots with remaining capacity.
- FR-23: identify required or overdue services through an approved maintenance tool and present its structured result.
- FR-24: check available service slots through approved application logic; results satisfy active-state and capacity rules.
- FR-27–29: bind tool calls to authenticated `request.user`, validate all arguments, and enforce permissions and ownership inside each tool.
- FR-31: record each executed tool attempt in AgentActionLog. Logging integration is explicitly deferred from this plan because central execution/registration is excluded; no production tool execution is enabled by this plan.
- FR-32: tool results have `success`, `code`, `message`, and relevant `data`.
- NFR-S01, NFR-S03, NFR-S04: authenticated private access, owner-scoped data, and role-based authorization.
- NFR-M01–M02: keep the handlers in `apps.ai_agent` and reuse application services rather than duplicating domain calculations.
- §4 RBAC matrix, §4.1: maintenance-check tool is for an Owner's own vehicles; available service slots are read-capable for Owner and Technician and manageable by Administrator; enforce role and ownership in handlers.
- §7 UJ-05: Owner asks about maintenance; the tool checks owned-vehicle history and returns a structured result.
- §8.4–8.6: tool argument schemas, structured result schema, authenticated identity binding, explicit permission checks, validation, allowlisting, least context, and safe failures.
- §9.5: keep normal application workflows before tool/LLM integration; Plan 007's manual booking is already implemented.

## Discovery Findings / Current-State Analysis

Baseline inspected on branch `feature/ai-read-tools`, HEAD `767630064621d0bc4f720aaea386a76d315c793a`; working tree was clean before this plan was created. The authoritative DOCX and only the requested relevant sources/plans/tests were inspected.

### Existing service interfaces and dependencies

- `apps.maintenance.services.get_vehicle_maintenance_overview(vehicle, as_of: date | None = None) -> dict` is HTTP-independent and read-only. It accepts a Vehicle object, not an actor or identifier, and does not authorize ownership itself. It returns `{"history": list[MaintenanceRecord], "due_services": list[DueServiceResult]}`. `DueServiceResult` contains `service_type`, `status`, `last_service`, `next_due_mileage`, `next_due_date`, and `reason`. The helper queries ServiceTypes once and MaintenanceRecords only for the supplied Vehicle, with related display objects loaded; the evaluator uses `timezone.localdate()` by default and performs no writes.
- `apps.appointments.selectors.get_available_service_slots() -> QuerySet[ServiceSlot]` is HTTP-independent and read-only. It filters `is_active=True` and `start_time > timezone.now()`, annotates one aggregate count of appointments in `ACTIVE_APPOINTMENT_STATUSES`, and excludes slots where capacity is exhausted. Model ordering is by `start_time`, then primary key. It takes no actor, ServiceType, or date argument and applies no authorization.
- Neither dependency requires an HTTP request. Their results are not directly safe tool payloads: the maintenance service returns Django model instances and dataclass objects; the slot selector returns a QuerySet and model instances. Each handler must adapt only approved fields into JSON primitives without exposing model objects or QuerySets.
- Existing tests exercise due calculation/history query bounds in `apps/maintenance/tests.py`, and slot filters/capacity/query count in `apps/appointments/tests.py`. Existing `apps/ai_agent/tests.py` covers AgentActionLog/sanitization, role-scoped context, structured chat responses, rejection of arbitrary registry names, and test-only dispatch. It has no tests for business read-tool handlers.

### Domain and validation facts

- `User.Role` values are `OWNER`, `TECHNICIAN`, and `ADMINISTRATOR`.
- Check-maintenance SRS schema is `vehicle_id: integer, required`; security boundary is authenticated Owner and ownership required. Resolve the Vehicle using `Vehicle.objects.filter(owner=actor, pk=vehicle_id)` before calling the service. A missing, malformed, cross-owner, or unknown identifier must return a safe failure without invoking the overview service or revealing which case occurred.
- Slot-list SRS schema is `service_type_id: integer, required; preferred_date: date, optional`. The SRS role matrix permits Owner and Technician read access to available slots and Administrator management access. Require an authenticated user with one of these domain roles; anonymous/invalid-role users are denied. This tool accepts no vehicle or user identity, so it has no vehicle ownership lookup. Do not silently narrow the documented slot read capability to Owner-only.
- For both identifiers, reject booleans, non-integers, non-ASCII/non-decimal strings if strings are accepted at the direct Python boundary, zero/negative values, missing keys, and unknown keys. Never accept `user_id`, `owner_id`, or caller-selected role. Use a positive existing `ServiceType` primary key for slot listing. `ServiceType` has no active flag; existing manual booking uses the complete `ServiceType.objects.all()` catalog and validates existence. Do not invent an active filter or duplicate all model validation for an existing row.
- The current `ServiceSlot` model has no direct `ServiceType` relation. Plan 007 explicitly forbids inventing one. The handler must validate that `service_type_id` identifies an existing `ServiceType`, then reuse `get_available_service_slots()` and its eligibility behavior exactly. Do not add service-based slot filtering or claim returned slots are linked/compatible with that ServiceType; current domain logic proves no such relationship. Do not add a date horizon or pagination; preserve Plan 007's all-qualifying-slots behavior.
- `preferred_date` is explicitly present in SRS §8.4 and is not implemented by the current selector. Plan 017 will validate this optional field using strict ISO calendar date `YYYY-MM-DD`, reject malformed strings and impossible calendar dates, and defer preferred-date filtering. Neither the SRS nor repository code defines how a date maps to timezone-aware `ServiceSlot.start_time`. Plan 017 must not invent UTC, server-local, user-local, or project-local behavior. A valid supplied date does not narrow the slots returned in this plan; do not claim it does.

### Plan 013/014 result and audit boundaries

- Plan 014's `ChatResult` and JSON endpoint use `success`, `code`, `message`, `data`, and `errors`; its initial explicit `TOOL_REGISTRY` was empty. Plan 016 subsequently registered `book_maintenance_appointment` with central audit handling. `execute_tool_request(name, arguments, *, actor, registry=None)` calls registered handlers with `handler(actor=actor, arguments=arguments)` and validates the five-key result contract. Plan 017 handlers return that contract and remain directly callable with this signature. They are not registered by Plan 017.
- `apps.ai_agent.models.AgentActionLog` requires `user`, `tool_name`, JSON-object `arguments` and `result`, `status` (`SUCCESS`/`FAILURE` matching `result.success`), nonnegative integer `duration_ms`, and auto-created `created_at`. `save()` calls `full_clean()`, which recursively sanitizes both JSON payloads using `apps.ai_agent.sanitization.sanitize_payload`; sensitive-key values are redacted, unsupported values/non-string keys and non-object top-level payloads are rejected. The User relation is protected. This model and its migration already exist.
- FR-31 audit recording belongs at the central execution boundary, not inside either handler: that boundary sees each attempted invocation (including pre-handler denial/validation), owns consistent timing/status/result capture, and prevents duplicate log rows if a handler is reused. Plan 017 excludes that boundary and the registry, so handlers must not create AgentActionLog records themselves. Direct handler tests are not production tool-execution integration. Until a later approved integration adds central logging before registration, these tools must remain unregistered/unavailable through chat and no claim is made that execution attempts are logged.

## Scope

- Add `apps/ai_agent/maintenance_tool.py`, exposing a direct `check_required_maintenance(*, actor, arguments)` handler.
- Add `apps/ai_agent/slot_tool.py`, exposing a direct `list_available_service_slots(*, actor, arguments)` handler.
- Add `apps/ai_agent/test_read_tools.py` for direct handler, authorization, ownership, validation, serialization, no-side-effect, and service/selector-reuse coverage.
- Return only JSON-native dictionaries/lists/scalars/null in the structured result. Use a stable safe success code and stable failure codes; errors must be sanitized and must not expose tracebacks or another user's data.
- Reuse `get_vehicle_maintenance_overview` and `get_available_service_slots`; do not recalculate due status or capacity inside tool modules.
- Keep each handler read-only, independently importable, authorization-aware, and directly testable.
- Do not modify the central Tool Registry; keep it empty and unchanged. End-to-end AI tool execution remains disabled until central audit capture and tool registration are implemented in a separately approved task.

## Out of Scope

- Registration, dispatch wiring, changes to `tools.py`, `agent.py`, `provider.py`, `views.py`, `urls.py`, `context.py`, `prompts.py`, chat JavaScript, or Chat template.
- AgentActionLog creation/execution integration; handlers do not write audit rows. A later central boundary task must implement FR-31 before any registered execution is enabled.
- Any booking/write tool, confirmation flow, cancellation, notification, or state mutation.
- New service-slot/service-type or service-slot/technician relationships, query fields, models, or migrations.
- Changes to the maintenance/appointment services, selector, models, migrations, SRS, README, docs, demo seed, or existing plans.
- LLM/provider integration, end-to-end AI execution, tool schemas sent to a provider, or claims that a user-visible chatbot can call these tools.

## Structured Result Contract

Every handler returns exactly the safe JSON-oriented contract used by the SRS and Plan 014:

```python
{
    "success": bool,
    "code": str,
    "message": str,
    "data": dict | None,
    "errors": dict | None,
}
```

- Success uses `success=True`, a stable success code, a safe human-readable message, JSON-native `data`, and `errors=None`.
- Expected invalid input, permission denial, or missing-object failure uses `success=False`, a stable code, a safe message, `data=None`, and either field-specific `errors` or `None`.
- No exception text, stack trace, model instance, QuerySet, date/datetime object, Decimal, or untrusted object is returned. Serialize dates and timestamps as ISO strings and monetary/private/unneeded fields are excluded.
- Maintenance data is limited to the SRS-relevant service identity/name, stable due status, last-service date/mileage when present, due thresholds as plain number/date strings, and deterministic reason. Do not return MaintenanceRecord notes, unrelated vehicle data, or technician/user details.
- Slot data may echo the validated ServiceType identity/name as request context, separately from the slot list. Return selector-qualified slots with IDs, ISO start/end times, and computed remaining capacity. Do not return appointments, owners, or raw active-count details. State through result wording/data semantics that slot eligibility is global and no direct service-to-slot relation or compatibility is established.

## Authorization and Validation Rules

### `check_required_maintenance`

- Require `actor.is_authenticated` and `actor.role == User.Role.OWNER` inside the handler; the upstream Chat endpoint is not a security boundary for the handler.
- Require exactly `vehicle_id`, then validate it as a positive integer primary-key value. Reject booleans and nonintegral/unsafe values.
- Retrieve only with `Vehicle.objects.filter(owner=actor, pk=vehicle_id).first()` (or equivalent owner-scoped lookup) before invoking the existing maintenance service. Missing and foreign-owned vehicles receive the same safe unavailable response. Never call the service for an unauthorized/missing Vehicle.
- Call `get_vehicle_maintenance_overview(vehicle)` and convert results to JSON primitives. This handler does not accept client `as_of`, service interval, status, or actor identity overrides.

### `list_available_service_slots`

- Require an authenticated actor whose domain role is allowed by the existing SRS matrix for this read capability: OWNER, TECHNICIAN, or ADMINISTRATOR. Do not use `is_staff` or `is_superuser` as domain authorization.
- Require `service_type_id`; allow only the optional `preferred_date` in addition. Validate both before selector access; resolve the ServiceType from existing rows. Reject unknown service IDs safely. Do not require or accept vehicle/user/owner identity.
- Accept `preferred_date` only as a real ISO calendar date string `YYYY-MM-DD`; reject datetime strings, impossible calendar dates, non-strings, and malformed values with a field error. Preferred-date filtering is deferred: even a valid supplied date does not narrow the selector results in Plan 017. Do not invent UTC, server-local, user-local, or project-local matching behavior.
- After validating the existing ServiceType, call `get_available_service_slots()` and use its annotation (`active_appointment_count`) to serialize remaining capacity. Preserve its active/future/capacity behavior and model ordering exactly; do not add service-specific filtering, per-slot count queries, arbitrary limits, pagination, or technician filtering.

## No-Side-Effect Requirements

- Both tools issue reads only. Tests must assert no Appointment, MaintenanceRecord, AgentActionLog, status, inventory, or other application data is created or changed by direct handler calls, including invalid/denied paths.
- Do not log to AgentActionLog inside handlers. No central integration is included and direct test invocation is not a production execution path.
- Do not claim these handlers are reachable from Plan 014 chat; the production registry contains the Plan 016 booking Tool, and these read handlers remain unregistered.

## Proposed Files and Responsibilities

- `.agents/plans/017-ai-read-tools.md` — this DRAFT plan only.
- `apps/ai_agent/maintenance_tool.py` — narrow argument/role/owner validation, call existing overview service, convert `DueServiceResult`/models into minimal structured JSON data.
- `apps/ai_agent/slot_tool.py` — validate actor, ServiceType and optional date; reuse global available-slot selector; serialize filtered eligible slots with remaining capacity.
- `apps/ai_agent/test_read_tools.py` — direct unit/database tests with mocked service/selector where useful and real PostgreSQL-backed fixtures for ownership/query behavior.

### Why separate handler modules instead of `read_tools.py`

Use the expected separate `maintenance_tool.py` and `slot_tool.py` modules. These tools have distinct input contracts, authorization semantics, serialization needs, and domain dependencies; separate modules make each independently importable and directly testable without creating a shared abstraction or editing the central registry. A combined `read_tools.py` would offer little reuse and make the required independent boundaries less explicit. Keep shared result construction local unless implementation demonstrates a small, justified helper; no fourth source file is planned.

## Expected Tests and Acceptance Criteria

### Maintenance tool

- Valid Owner-owned Vehicle calls `get_vehicle_maintenance_overview` exactly once and returns JSON-round-trippable success data for due, overdue, not-due, and no-history outcomes using service result values.
- Anonymous, Technician, and Administrator actors are denied; invalid/missing/extra arguments and malformed, boolean, zero, negative, unknown, or cross-owner Vehicle IDs fail safely.
- Foreign/missing IDs yield indistinguishable safe failures, make no service call, and disclose no foreign Vehicle/history data.
- Result contains no model instances, QuerySets, maintenance notes, technician identity, credentials, stack traces, or private data beyond required SRS output.

### Slot tool

- Authenticated Owner, Technician, and Administrator domain roles can read; anonymous users and invalid roles are denied, independent of staff/superuser flags.
- Required/extra/malformed arguments, invalid or missing ServiceType, and invalid preferred dates return stable safe field errors without selector invocation where argument validation fails.
- Reuses `get_available_service_slots()` once; returned slots are only active, future, capacity-available slots as selected by that function, have accurate remaining capacity, and preserve start-time/PK order.
- A supplied preferred date is strictly validated as `YYYY-MM-DD`; malformed strings and invalid calendar dates are rejected. Filtering by preferred date is explicitly deferred because its matching semantics against timezone-aware slot times are undefined. The successful slot list remains the selector's unchanged global result, regardless of the valid preferred-date value; do not claim the preference was applied. No service-slot relationship is assumed; any existing ServiceType is validated but does not narrow the global slot selector.
- Verify JSON round trip and absence of Model instances, QuerySets, notes, appointment/owner details, credentials, and exception text.

### Shared / regression

- Both handlers return all five result keys with correct types and safe JSON-compatible values for success and failure.
- Direct invocation creates no AgentActionLog or business writes. Keep both Plan 017 read handlers absent from the production registry; the existing Plan 016 booking Tool remains its sole entry and unregistered names remain rejected.
- Existing due-service and slot-selector tests remain unchanged and continue to exercise their underlying services/selectors.
- Tests must not imply end-to-end agent execution or audit recording.

Acceptance is satisfied only when both handlers are independently importable/directly tested, reuse the exact existing domain functions, enforce their distinct SRS role/ownership boundaries, validate all arguments, return the structured contract, perform no writes, and remain unregistered.

## Risks and Problems

- Maintenance service has no authorization and returns model-bearing objects. A missing owner-scoped lookup or incomplete serializer could leak another Owner's information or ORM values; test service-call ordering and JSON round trips.
- The slot selector has no actor, ServiceType, or date awareness. The handler must enforce the role boundary and treat selected ServiceType as validated context only; no compatibility relation exists. A future SRS/schema change would be required for service-specific slot compatibility.
- SRS says `preferred_date` is type `date` but does not state how it matches timezone-aware slot start times; repository search found no existing date-matching contract. Plan 017 implements strict `YYYY-MM-DD` validation and rejects malformed or impossible calendar dates, but defers filtering. It must not invent UTC, server-local, user-local, or project-local behavior.
- FR-31 remains a mandatory system requirement. Since central dispatch and registry edits are expressly excluded, these functions must not be exposed for production invocation until a later approved task adds audit-attempt recording at the central execution boundary.
- The current dispatcher checks only part of the five-key contract. This plan's tests establish the handler contract but do not change dispatcher validation; registry integration should separately validate/log the full result contract.
- SRS §8.4 says slots are returned “for a selected service” while the accepted Plan 007 and current `ServiceSlot` model have no direct ServiceType relation. Validate that `service_type_id` exists, then reuse Slot Discovery exactly; returned availability is global and not a claim of service-specific compatibility.

## Alternatives Considered

### Option A — Separate thin read-only handlers over existing domain interfaces (recommended)

Keep due calculations and slot eligibility in the tested services/selectors; handlers do authorization, input validation, and serialization only. Leave central registration and audit integration deferred.

Advantages: reuses tested rules, keeps the tools independently testable, and avoids duplicated business logic/schema changes. Disadvantages: handlers cannot be invoked by production chat until registry and audit integration are separately approved and completed.

### Option B — Put domain calculations and authorization in one combined module or central dispatcher

Advantages: may centralize common result handling. Disadvantages: duplicates existing service behavior or expands into explicitly excluded registry/dispatch files, obscures distinct role rules, and couples direct handler imports to chat execution.

## Recommended Approach

Choose Option A. The repository already has stable, tested, HTTP-independent domain interfaces for due-service calculation and slot discovery. Thin modules should own the actor/argument boundary and adapt their outputs to SRS JSON results. Keep the Plan 016 central registry/logging unchanged; no production execution of these read handlers is possible or claimed until a later plan adds registration and FR-31 audit integration at the central boundary.

## Implementation Steps

1. Add the focused read-tool test module and define direct-call fixtures for all three roles, owned/foreign Vehicles, ServiceTypes, due results, and eligible slots.
2. Implement the Owner-only maintenance handler: strict argument validation, scoped Vehicle resolution, service reuse, minimal JSON serialization, and safe structured failures.
3. Implement the SRS-role-authorized slot handler: strict ServiceType/date validation (including malformed and invalid calendar-date rejection), one unchanged selector call, remaining-capacity serialization, and safe structured failures. Do not filter results by preferred date in Plan 017.
4. Run focused tool tests, existing maintenance/slot-selector regression tests, AI-agent tests, Django check, migration check, full suite, and whitespace/diff boundary review; verify neither read handler is registered and migration state is unchanged.
5. Complete the Implementation Report and change plan status only after required validation passes. Do not register tools or claim audit/end-to-end execution.

## Test Plan and Validation Sequence

After approval, use the repository-local interpreter and configured PostgreSQL environment. Run the smallest new handler test targets first; then existing relevant domain tests; then `apps.ai_agent.tests`; then the full project suite; then `manage.py check`, `manage.py makemigrations --check`, `git diff --check`, migration inspection, and final scope review. Stop at first failure and report the exact error; do not switch to SQLite or alter environment configuration. Exact class/method labels should follow the names created in the implementation test module.

Required checks include:

- Authorization and foreign Vehicle isolation for maintenance.
- Slot role matrix, ServiceType existence, strict date wire format and invalid-calendar-date rejection, and stable ordering. Test that a valid `preferred_date` does not narrow selector results in Plan 017. Do not test or invent timezone-based matching.
- Safe serialization, all five result keys, no side effects, no per-slot count queries, and no unexpected exception leakage.
- Existing due-service and selector tests plus structured-result and unregistered-name regression tests.
- `python manage.py check`; `python manage.py makemigrations --check`; full PostgreSQL test suite; `git diff --check`; migration-directory/diff inspection.

## Migration and Environment Impact

MIGRATIONS_EXPECTED: NO. Existing Vehicle, ServiceType, MaintenanceRecord, ServiceSlot, Appointment, and AgentActionLog schema already supports this read-only scope. No model, migration, dependency, setting, environment variable, or persistent database change is required. No HTTP route or URL change is required. PostgreSQL remains the configured test backend; reads need no concurrency test or transaction.

## Dependencies and Conflicts with Existing Plans

- Plan 006 is IMPLEMENTED and supplies the due-service service/results; reuse its exact interface and preserve its read-only calculation semantics.
- Plan 007 is IMPLEMENTED and supplies the available-slot selector and exact eligibility definition (`is_active`, `start_time > timezone.now()`, remaining capacity counted using active statuses). Do not reimplement its query or alter its no-service-relation rule.
- Plan 013 is IMPLEMENTED and supplies AgentActionLog plus recursive JSON sanitization. Its schema is not changed; this plan does not call it because audit belongs in the deferred central execution boundary.
- Plan 014 initially left the production registry empty; Plan 016 now registers the audited booking Tool. Do not register the Plan 017 read tools or modify central AI dispatch in this task.
- No dependency on Plan 015 frontend/docs work. No models or migrations are required.

## Open Questions

- The `preferred_date` wire format is strict `YYYY-MM-DD`; malformed and impossible calendar dates are rejected. Preferred-date filtering is deferred because neither the SRS nor repository defines how a calendar date matches a timezone-aware slot start time. Resolve this before a later implementation of date filtering; Plan 017 must not invent timezone behavior.
- The SRS wording “for a selected service” conflicts with the current no-relation data model and Plan 007's explicit decision not to invent one. This plan follows the existing model/Plan 007: validate and identify ServiceType, but return globally eligible slots. If true service-specific compatibility is required, stop and create a separate requirements/schema decision before implementation.
- FR-31 audit recording is intentionally deferred from Plan 017. Before either tool is registered or called by a production execution path, approve and implement central audit capture for every attempted invocation. This is not a blocker to building isolated, unregistered handlers.

## Approval

- Decision: APPROVED
- Approved by: User
- Approval date: 2026-09-28

Implementation must not begin while Status is `DRAFT` or Decision is `PENDING`.

## Implementation Report

Not implemented. This document records discovery and proposed scope only.
