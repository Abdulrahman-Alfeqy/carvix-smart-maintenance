# Plan: Owner Maintenance History and Due-Service Overview

## Metadata

- Status: APPROVED
- Related issue: N/A
- Owner: Arwa
- Reviewer: Abdalrahaman Atef
- Branch: feature/owner-maintenance-history-due-service
- Created: 2026-09-25
- Last updated: 2026-09-25

## Objective

Extend the existing Owner Vehicle detail page to show maintenance history and calculated service status for that Vehicle. Calculate statuses at request time from the selected Vehicle's current mileage, its recorded MaintenanceRecords, and each ServiceType's kilometer and calendar-month intervals. Keep the workflow read-only, owner-scoped, and reusable by a future maintenance-check tool. Do not persist calculated status.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`.

- FR-08 — Owners view maintenance history for their Vehicles; records are filtered by Vehicle ownership. Acceptance criterion: records are filtered by vehicle ownership. (§2, Table 4)
- FR-11 — Calculate due or overdue maintenance using configured intervals and recorded history. Acceptance criterion: result includes service, status, last service, and reason. (§2, Table 4)
- NFR-S01 — Private pages and endpoints require authentication. (§3, Table 5)
- NFR-S03 — Owner data access is constrained by `request.user` ownership. (§3, Table 5)
- NFR-S04 — Role checks prevent vertical privilege escalation. (§3, Table 5)
- NFR-P02 — Use `select_related` or `prefetch_related` where suitable. (§3, Table 5)
- NFR-M02 — Business logic resides in services or model-domain functions rather than templates. (§3, Table 5)
- Table 6 — The Vehicle Owner may read own maintenance history; Technician does not receive this Owner capability; Administrator may manage records. (§4, Table 6)
- Table 11 and §6.4 — Use the existing Vehicle, ServiceType, and MaintenanceRecord data; derived due state is calculated and not duplicated in storage. (§6.2 and §6.4)
- UJ-03 — Verify the selected Vehicle's ownership, load its maintenance records, and display history and due indicators. (§7, Table 12)

## Current-State Analysis

- `apps/vehicles/views.py` defines an authenticated OWNER-only `VehicleDetailView`. Its `get_queryset()` filters by `owner=self.request.user`; another owner's Vehicle therefore returns 404.
- The view renders `templates/vehicles/vehicle_detail.html`, which currently displays Vehicle details without maintenance history or calculated service indicators.
- `apps/maintenance/models.py` defines `ServiceType.interval_km` as `PositiveIntegerField()` and `interval_months` as `PositiveIntegerField()`. Neither field sets `null=True` or `blank=True`, so both are required. Database check constraints require each to be greater than zero; `ServiceType.clean()` also rejects values less than or equal to zero. `NOT_CONFIGURED` is unreachable for valid stored ServiceTypes and is excluded from the status vocabulary.
- `MaintenanceRecord` requires a Vehicle, ServiceType, TechnicianProfile, Appointment, service date, and mileage. Its model validation rejects future service dates and its database check rejects negative service mileage. Its default order is newest service date, then newest primary key; it has an index on `(vehicle, service_date)`.
- The current data model permits multiple records per Vehicle and ServiceType. The calculation must explicitly select the latest by `service_date`, then primary key.
- Existing Admin registrations provide CRUD for `ServiceType` and `MaintenanceRecord`, with model validation in Admin forms. They are sufficient for test and demo data setup; no new Admin interface is needed.
- Existing tests cover Vehicle detail authorization and ownership and Maintenance model validation. No calculation service exists.
- Plans 000 through 005 exist; 006 is the next plan number. The user-selected task combines history and due-service calculation, expects no migration and no transaction, and has MEDIUM review size.

## Scope

- Add a read-only calculation module at `apps/maintenance/services.py`.
- Display the selected Vehicle's maintenance history and one calculated status per ServiceType on the existing owner-scoped Vehicle detail page.
- Use exactly these stable status string values: `NO_HISTORY`, `NOT_DUE`, `DUE`, and `OVERDUE`.
- Calculate status and thresholds in memory; do not add or persist a status field.
- Use standard-library calendar arithmetic and a controllable date input for deterministic tests.

## Out of Scope

- MaintenanceRecord create, update, or delete; Technician completion workflow.
- Manual booking, ServiceSlot display, appointment management, and capacity logic.
- Custom Administrator interfaces, new Admin behavior, new dashboards, or generic RBAC framework.
- Inventory mutation, AgentActionLog, AI tools, Chat UI, and LLM integration.
- Stored due status, a `DUE_SOON` status, speculative recommendations, ServiceType redesign, or new dependencies.
- New URLs, forms, models, or migrations.

## Status Definitions and Calculation Algorithm

Status values are plain stable strings in returned results, suitable for direct unit testing and later service reuse. Status is never written to the database.

For each ServiceType in predictable name/primary-key order:

1. Find that Vehicle's latest MaintenanceRecord for the ServiceType, ordered by descending `service_date` and then descending primary key.
2. If no record exists, return `NO_HISTORY`, `last_service=None`, `next_due_mileage=None`, and `next_due_date=None`. Do not infer a due state from Vehicle creation, zero mileage, or activity before CARVIX. Use a deterministic reason that no recorded maintenance history is available for that service.
3. With a record, compute `next_due_mileage = mileage_at_service + interval_km` and `next_due_date = service_date + interval_months` using the calendar-month rule below.
4. Evaluate mileage and date independently. Mileage is unavailable/inconsistent when `Vehicle.current_mileage < mileage_at_service`; in that case, do not calculate a negative traveled distance and do not mark due from mileage. Keep the known threshold result available for display, explain that current mileage is below the latest service mileage, and continue date evaluation.
5. For an available mileage dimension: current mileage below the threshold is `NOT_DUE`; equal is `DUE`; above is `OVERDUE`.
6. For the date dimension: the as-of date before the threshold is `NOT_DUE`; equal is `DUE`; after is `OVERDUE`.
7. Combine available dimension results by precedence `OVERDUE` > `DUE` > `NOT_DUE`. Since both interval fields are required and positive, both thresholds are available whenever history exists; only the mileage comparison can be unavailable because of inconsistent readings. If date is not due and mileage is unavailable, return `NOT_DUE` with the inconsistency reason, without claiming a mileage result.
8. Build the reason deterministically in mileage-then-date order. For each available dimension, report its classification and threshold, including a `NOT_DUE` dimension when the other dimension determines the combined status; this preserves both contributing facts in mixed cases. If mileage is inconsistent, report mileage as unavailable with the current and latest-service mileage values, and include that explanation even when the date dimension determines the final status. For `NO_HISTORY`, use a deterministic no-record explanation and no thresholds. Do not add `DUE_SOON` or another status.

The as-of date defaults to `django.utils.timezone.localdate()`. Keep ORM loading and pure calculation separate within the focused service module: the read-only service loads the selected Vehicle's ServiceTypes and records, then passes those prepared inputs plus an explicit as-of date to a pure evaluator. Tests can call the evaluator with a fixed date without a new dependency or database clock dependency.

Use stable reason components and a fixed order: `Mileage: <classification> (current <value>, next due <threshold>). Date: <classification> (as of <date>, next due <threshold>).` Omit the mileage threshold comparison when mileage is inconsistent and instead report `Mileage: unavailable (current <value> is below latest service <value>).` The combined status still follows the precedence above. The exact prose may be phrased naturally in the UI, but these values, classifications, and ordering must remain deterministic.

## Calendar-Month Arithmetic

Use a small helper in `apps/maintenance/services.py` and only Python standard-library calendar/date utilities. To add `interval_months` to `service_date`, calculate the target year and month arithmetically, preserve the original day if valid, and otherwise clamp to the target month's final valid day using `calendar.monthrange`.

Examples: January 15 plus one month is February 15; January 31 plus one month is the last valid day of February (February 28 or 29 as appropriate). Do not approximate a month as 30 days. No package is needed.

## Latest-Record and Inconsistent-Mileage Rules

- Latest means newest `service_date`; on a tie, newest primary key.
- Both the displayed history and all calculation input records are filtered by the already selected Vehicle. Never choose a record by ServiceType without also constraining it to that Vehicle.
- When current mileage is below the latest record's mileage, mileage does not contribute `DUE` or `OVERDUE`; no negative distance is produced. Evaluate the date threshold normally and include a deterministic reason that current mileage is below the latest service mileage. Do not alter either record or add a model rule/migration.

## Query and Performance Design

The calculation accepts an already-authorized Vehicle object and executes a bounded query plan:

1. Load all ServiceTypes once, ordered by `name`, then primary key.
2. Load only MaintenanceRecords with `vehicle=vehicle`, ordered by descending `service_date`, then descending primary key; use `select_related("service_type", "technician__user")` for displayed relations.
3. Reuse that single record result list both for history display and to select the first/latest record for each ServiceType. Do not issue a query per ServiceType.

The page history is sourced from that same Vehicle-filtered result. This avoids N+1 relation loads and prevents cross-Vehicle records from appearing in history or calculations.

## Authorization and Security Design

- Preserve `LoginRequiredMixin`, the OWNER role check, and `VehicleDetailView.get_queryset()` filtering by `request.user`.
- Resolve the requested Vehicle through the owner-scoped queryset before calling the calculation service. Service calculation begins only after this retrieval succeeds.
- The service performs no authorization decision, accepts no client-provided owner/user identity, performs no writes, and returns data only for the Vehicle argument it receives.
- Anonymous access redirects to login; TECHNICIAN and ADMINISTRATOR are forbidden on this Owner page; another Owner's Vehicle returns 404.
- Render notes and other record fields with Django template autoescaping. Do not mark user-controlled values safe.
- No browser state changes are introduced; existing read-only GET behavior remains read-only.

## Service, View, and Template Design

- `apps/maintenance/services.py`: contain one focused read-only module. Separate the bounded ORM-loading function from a pure evaluator in this same module. The evaluator receives prepared Vehicle mileage, ServiceType intervals, the latest matching record (or no record), and an explicit as-of date; it performs no queries or writes. The service returns prepared dictionaries or result objects containing the ServiceType, stable status value, latest record/last service, next due mileage/date where available, and deterministic reason components. It may expose a small month-add helper for focused unit testing. Do not also create `selectors.py`.
- `apps/vehicles/views.py`: extend the existing `VehicleDetailView` context only after the owner-scoped object has been resolved. Call the maintenance service with `self.object`; provide both history and status results to the template.
- `templates/vehicles/vehicle_detail.html`: add clearly labeled history and due-service sections. Render status, ServiceType, last service, applicable thresholds, reason, and available history fields (service type, service date, mileage, technician when available, notes when available). Render a clear empty-history state. For each ServiceType with no record, render `NO_HISTORY` and its deterministic explanation. Keep standard autoescaping. No URL or form change is needed.

## Expected Files

- `apps/maintenance/services.py` — new focused calculation module.
- `apps/maintenance/tests.py` — calculation, calendar arithmetic, and status tests.
- `apps/vehicles/views.py` — add context to the existing owner-scoped detail view.
- `apps/vehicles/tests.py` — page integration, isolation, rendering, and authorization regression tests.
- `templates/vehicles/vehicle_detail.html` — render history and statuses.
- `.agents/plans/006-owner-maintenance-history-due-service.md` — this plan.

No forms, URLs, models, migrations, Admin interfaces, or other source files are expected. The existing View, template, maintenance app, and two relevant test files are sufficient.

## Alternatives Considered

### Option A — Combined history and due-service overview

Extend the existing owner-scoped Vehicle detail page and implement one read-only maintenance calculation service. This completes UJ-03 in one coherent slice and uses the existing domain schema.

### Option B — History only, defer due calculation

Deliver FR-08 without FR-11. This reduces calculation work but leaves the expected UJ-03 outcome incomplete and would require revisiting the same page and records query.

## Recommended Approach

Choose Option A. The human-approved behavior defines no-history results, status boundaries and precedence, calendar arithmetic, and inconsistent mileage. The model already provides both required intervals as non-null positive values. A single read-only service, called only after owner-scoped Vehicle resolution and backed by a bounded query, completes the Owner's maintenance overview without schema or Admin changes.

## Implementation Order

1. Add the pure calendar-month helper and calculation service in `apps/maintenance/services.py`.
2. Add service-level tests in `apps/maintenance/tests.py` for every status, threshold, tie-breaker, date rule, and inconsistent mileage case.
3. Extend `VehicleDetailView` after owner-scoped object retrieval and render prepared history/results in `vehicle_detail.html`.
4. Add Owner page integration and authorization/isolation tests in `apps/vehicles/tests.py`.
5. Run the tests and project checks listed below, verify no migration is generated, and inspect the final diff.

## Test Plan

### Authorization and Isolation

- Anonymous access redirects to login.
- OWNER can access an owned Vehicle.
- TECHNICIAN and ADMINISTRATOR receive 403.
- Another Owner's Vehicle returns 404.
- The response contains none of another Vehicle's records or calculated data.
- Verify calculation is called only after owner-scoped Vehicle retrieval succeeds; cross-owner requests do not invoke it.

### History

- Selected Vehicle history is displayed; records from another Vehicle are excluded.
- Empty history state is rendered.
- History ordering is deterministic by newest service date, then newest primary key.
- ServiceType, service date, mileage, technician when available, and notes when available are rendered safely.
- Multiple ServiceTypes remain independent.
- Multiple records for one ServiceType use newest service date and newest primary key as tie-breaker for calculation.

### Calculation

- No history returns exactly `NO_HISTORY`; last service and next due thresholds are `None`; no due/overdue classification is made.
- Mileage below its threshold returns `NOT_DUE` when date is also not due.
- Mileage exactly at threshold returns `DUE`; mileage above threshold returns `OVERDUE`.
- Date before threshold returns `NOT_DUE` when mileage is also not due.
- Date exactly at threshold returns `DUE`; date after threshold returns `OVERDUE`.
- Mileage `DUE` with date `NOT_DUE` returns `DUE`; date `DUE` with mileage `NOT_DUE` returns `DUE`.
- One dimension `OVERDUE` and the other `DUE` returns `OVERDUE`; both `OVERDUE` returns `OVERDUE`.
- Reasons are deterministic and ordered mileage then date; for each available dimension they include its classification and threshold, including a `NOT_DUE` dimension in mixed cases. Inconsistent mileage is reported as unavailable with the compared mileage values; `NO_HISTORY` has a deterministic no-record explanation and no thresholds.
- Calendar month arithmetic covers January 15 plus one month and January 31 clamping, including leap and non-leap February.
- Current mileage below latest service mileage produces no negative traveled distance, does not make mileage `DUE`/`OVERDUE`, explains the inconsistency, and still evaluates date independently.
- Status values are derived in memory; no status field or write is introduced.
- Tests inject a fixed as-of date into the calculation; no new time-control dependency is added.
- Test the model-backed fact that both interval fields are required and positive; there is no `NOT_CONFIGURED` status.

### Regression and Validation

- Existing Vehicle tests pass.
- Existing Maintenance tests pass.
- Full PostgreSQL suite passes.
- `python manage.py check` passes.
- `python manage.py makemigrations --check` reports no changes.
- Migration-directory inspection confirms no new migration.
- `git diff --check` passes.

Run the smallest relevant tests first, then the complete suite. These commands are for the approved implementation phase and are not run during plan correction.

## Risks and Problems

- Incorrect vehicle scoping could disclose another owner's data. Use only the existing owner-scoped Vehicle lookup and constrain every history query to its resulting object.
- N+1 queries could affect page performance. Load ServiceTypes once and related MaintenanceRecord data in one Vehicle-filtered query with `select_related`.
- Calendar boundaries can produce inconsistent status if months are approximated as days. Use the specified clamped calendar-month addition.
- Odometer correction or data entry may place current mileage below the last service mileage. Suppress the mileage determination, avoid negative distance, explain the issue, and still evaluate the date dimension.
- The database model requires both intervals and enforces positive values. `NOT_CONFIGURED` is not a valid state for valid stored rows and must not be implemented.
- This workflow does not create MaintenanceRecords; Admin remains the current test/demo data path until a separately planned technician workflow exists.

## Migration and Environment Impact

MIGRATIONS_EXPECTED: NO. No model or stored status changes are planned. No environment-variable or dependency changes are planned. Use the Python standard library for month arithmetic and Django's local-date utility for the default as-of date. Verify `python manage.py makemigrations --check` and inspect the migration directory during implementation.

## Rollback Strategy

Revert the calculation module, Vehicle detail context integration, template sections, and associated tests. No schema, stored state, dependency, URL, or environment rollback is needed.

## Definition of Done

- The Owner detail page displays only the selected owned Vehicle's maintenance history and its calculated service statuses.
- All statuses and reasons follow the approved no-history, threshold, precedence, calendar-month, latest-record, and inconsistent-mileage rules.
- Authorization and isolation tests pass, including no calculation for unauthorized cross-owner requests.
- The relevant Maintenance and Vehicle test suites and full PostgreSQL suite pass; Django check, no-migration check, migration inspection, and whitespace check pass.
- No model, migration, URL, form, Admin interface, stored status, AI, or out-of-scope workflow is added.
- Implementation matches this plan; the plan is changed to `IMPLEMENTED` only after all required tests are complete.

## Open Questions

None blocking.

Resolved decisions:

- History and due-service overview form one vertical slice.
- Services without history use `NO_HISTORY`.
- `NO_HISTORY` is not automatically `DUE` or `OVERDUE`.
- `Vehicle.created_at` is not a maintenance baseline; zero mileage and pre-CARVIX service are not assumed.
- Equality is `DUE`; exceeding a threshold is `OVERDUE`.
- Mileage and date are evaluated independently; either may trigger the result.
- `OVERDUE` takes precedence over `DUE`, which takes precedence over `NOT_DUE`; reasons identify all triggering dimensions.
- Calendar-month arithmetic with end-of-month clamping is used, not fixed 30-day arithmetic.
- When current mileage is below the latest service mileage, mileage is unavailable/inconsistent, no negative distance is produced, and date is still evaluated.
- Latest record means newest service date, then newest primary key.
- Both ServiceType interval fields are required and positive; `NOT_CONFIGURED` is not part of the public status vocabulary.
- Derived status is not stored.
- Existing Django Admin is sufficient for test and demo data setup; no custom Administrator interface is included.
- The workflow is read-only and requires no transaction.
- No migration is expected.
- General RBAC and AI remain deferred.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-25

Implementation must not begin while Status is `DRAFT` or Decision is `PENDING`.

## Implementation Report

Complete this section after implementation.

- Summary:
- Files changed:
- Tests executed:
- Test results:
- Migration/environment changes:
- Security checks:
- Remaining risks:
- Deviations from plan:
