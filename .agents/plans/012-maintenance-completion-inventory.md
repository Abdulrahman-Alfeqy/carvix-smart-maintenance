# Plan: Technician Maintenance Completion and Inventory

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/maintenance-completion-inventory
- Created: 2026-09-27
- Last updated: 2026-09-27

## Objective

Implement the approved Technician start-service and maintenance-completion workflow for assigned Appointments: record service date, mileage, notes, and any SpareParts used; create the MaintenanceRecord and MaintenancePart rows; reduce inventory atomically; and apply only the three human-approved status transitions.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`, Version 1.0, Initial Approved Baseline.

- FR-10: Technicians create MaintenanceRecords for assigned appointments; the record links vehicle, service, technician, mileage, and appointment.
- FR-17: Technicians update assigned Appointment status, accepting only valid transitions. The requirement gives no transition edges or eligible source states.
- FR-20 (Should): Technicians record parts used during completed maintenance through MaintenancePart, with non-negative inventory.
- §4.1 and §4.2 authorization rules: filter Technician appointments by `technician__user=request.user`; role permissions deny unauthorized access.
- §6.2, Table 11: MaintenanceRecord fields are vehicle, service_type, technician, appointment, service_date, mileage_at_service, notes; SparePart quantity is non-negative; MaintenancePart quantity_used is positive and each record/part pair is unique.
- §6.3: inventory updates may not produce negative quantity; mileage cannot be lower than accepted prior mileage without Administrator resolution; history is retained safely.
- §6.4: MaintenancePart is the many-to-many join carrying quantity_used.
- UJ-07: Technician opens an assigned appointment, starts service, records notes and parts, marks it completed, and creates a maintenance record; expected outcome is a completed appointment and updated history.
- NFR-R01: multi-write inventory operations use atomic transactions and roll back on induced failure.

## Current-State Analysis

- The current branch `feature/maintenance-completion-inventory` points at the updated main baseline. Git history shows Plan 010 Demo Seed Data was merged by PR #17 (`1c2f1eb`, `9e4c5e3`); this plan does not modify demo files or credentials.
- Plan 011 is IMPLEMENTED. It provides assigned-only Technician Appointment list/detail reads and deferred mutation because FR-17 has no exact transition graph. The human resolution supplies the narrow transition mapping for this plan.
- `Appointment.status` stores PENDING, CONFIRMED, IN_PROGRESS, COMPLETED, and CANCELLED. These choices describe stored values only. Existing `ACTIVE_APPOINTMENT_STATUSES` is used for booking/capacity rules, not completion eligibility.
- `Appointment.technician` is nullable. Technician detail reads scope the queryset to the current TechnicianProfile; nonexistent, unassigned, and another Technician's appointments resolve as 404.
- `MaintenanceRecord` has the SRS fields and links to Vehicle, ServiceType, TechnicianProfile, and Appointment. `clean()` checks future dates, negative mileage, and consistency of vehicle/service/technician with its Appointment. There is no uniqueness constraint on `appointment`; multiple records per Appointment are currently allowed.
- `MaintenancePart` stores a positive quantity and has a database uniqueness constraint on `(maintenance_record, spare_part)`.
- `SparePart.quantity` is non-negative by model validation and database check constraint. No completion service currently locks inventory or coordinates record creation and stock reduction.
- Existing services use `transaction.atomic()` and `select_for_update()` where their workflows need serialization. PostgreSQL-specific transaction/concurrency tests use `TransactionTestCase` and skip only when the configured database is not PostgreSQL. CSRF tests use Django `Client(enforce_csrf_checks=True)`.
- The SRS requires the assigned Technician to start service, update status, record completion details and parts, create history, and finish with Appointment status COMPLETED. The exact mapping to stored statuses is not explicit SRS text. Human resolution by Abdalrahaman Atef (2026-09-27) approves only PENDING -> IN_PROGRESS, CONFIRMED -> IN_PROGRESS, and IN_PROGRESS -> COMPLETED.

## Completion Semantics and Eligibility

- Successful completion must persist a MaintenanceRecord and set the authorized Appointment status to COMPLETED, as stated in UJ-07. The status update is not independently optional for a successful completion.
- A Technician may start service only from PENDING or CONFIRMED; the resulting status is IN_PROGRESS.
- A Technician may complete maintenance only from IN_PROGRESS; the resulting status is COMPLETED. PENDING and CONFIRMED cannot complete directly; COMPLETED and CANCELLED cannot be started or completed.
- These exact edges are the human-approved resolution of an SRS ambiguity, not literal SRS transition text. No other transition is approved. Revalidate every edge after locking the Appointment.

## Authorization and Assignment Isolation

For the approved workflow:

- Anonymous requests redirect to login; only TECHNICIAN is allowed. OWNER and ADMINISTRATOR receive 403.
- Require the authenticated TECHNICIAN's TechnicianProfile; a missing profile receives safe denial.
- Resolve Appointment only from a queryset scoped to `technician=request.user.technician_profile`. Another Technician's, unassigned, and nonexistent IDs return 404 without cross-object disclosure.
- Derive Vehicle, ServiceType, TechnicianProfile, and Appointment only from the authorized Appointment and authenticated user. Ignore any client-supplied owner_id, technician_id, user_id, relationship IDs, or record ID.
- Endpoint authorization is enforced server-side regardless of template visibility.

## MaintenanceRecord Field Derivation

- `appointment`: authorized URL object, re-fetched under lock.
- `vehicle`: `appointment.vehicle`.
- `service_type`: `appointment.service_type`.
- `technician`: `request.user.technician_profile`, revalidated as the Appointment assignee.
- `service_date`: server-derived completion date using `timezone.localdate()`; the client cannot choose a date. Existing model validation rejects future dates.
- `mileage_at_service`: explicit allowlisted, required non-negative integer. Reject mileage below `Vehicle.current_mileage` pending Administrator resolution, consistent with the SRS prior-mileage rule. Existing model validation also rejects negative mileage.
- `notes`: explicitly allowlisted optional text. Do not accept Appointment notes or relation fields as a substitute.
- Validate relationship consistency using the existing model validation. Failed operation leaves no MaintenanceRecord.

## Parts Input Design

FR-20 and UJ-07 place used parts in this workflow, so after eligibility is resolved the narrow input is a repeated form row of `spare_part_id` plus positive integer `quantity_used` (empty rows ignored if present by form design).

- Explicitly reject duplicate SparePart identifiers, missing/nonexistent parts, zero or negative quantities, malformed/non-integer quantities, and insufficient stock.
- Do not accept price, inventory totals, a MaintenanceRecord identifier, or any relationship/actor identifier as authority.
- Resolve all SpareParts from server-side records. Validate all submitted entries before creating MaintenancePart rows.
- Use Django forms and existing project conventions; no JavaScript framework or dependency.

## Transaction, Locking, and Duplicate Prevention

Use one `transaction.atomic()` for the complete completion operation:

1. Re-fetch and lock the assigned Appointment; revalidate assignment and the approved eligibility condition after locking.
2. Validate the complete parts payload (including duplicate IDs and positive quantities).
3. Re-fetch and lock all selected SpareParts in deterministic primary-key order.
4. Check every stock balance before writing any stock change.
5. Create and validate the MaintenanceRecord from server-derived relationships.
6. Create MaintenancePart rows and reduce SparePart quantities without permitting negatives.
7. Set Appointment status to COMPLETED only because UJ-07 requires that successful outcome and the source eligibility is approved.
8. Confirm persisted state before returning success.

Any failure rolls back status, MaintenanceRecord, MaintenancePart rows, and all stock changes. Known domain rejections are raised only after the atomic block has rolled back if subsequent queries are needed. Translate only a named, understood expected database constraint; propagate unrelated IntegrityError, DataError, OperationalError, and programming defects.

Current schema has no uniqueness constraint for `MaintenanceRecord.appointment`, so it permits multiple MaintenanceRecords per Appointment. Re-fetching/locking the Appointment serializes this workflow on PostgreSQL; inside the lock, reject if an existing MaintenanceRecord is present. Do not add a uniqueness constraint or migration merely for convenience. Direct concurrent writers that bypass this service are not protected by a DB-level one-record-per-appointment rule; adding such a constraint requires separate SRS justification and approval.

## Expected Domain Errors

Safe, user-facing failures should cover permission denied, appointment unavailable, appointment not eligible under the approved predicate, already completed/recorded, invalid mileage/date/notes, invalid or duplicate part selection, missing part, malformed quantity, non-positive quantity, and insufficient stock. Do not reveal unrelated Appointment, Vehicle, Owner, or inventory data.

Unexpected database and programming errors must not be converted into a false success or swallowed as ordinary validation errors. Known expected constraint failures may be translated only after identifying the exact constraint and ensuring rollback.

## Proposed Changes

As approved:

- `apps/appointments/forms.py`: add explicit allowlisted completion fields and narrow parts input.
- `apps/appointments/services.py`: add narrow Technician start-service and completion domain services with locking, revalidation, field derivation, duplicate prevention, all-parts validation, stock updates, and structured safe errors.
- `apps/appointments/views.py` and `apps/appointments/urls.py`: add assigned-only POST start-service and GET completion form/POST completion endpoints; GET remains read-only and mutations are CSRF-protected POST only.
- `templates/appointments/technician_appointment_detail.html`: show start/completion controls only for eligible status; authorization remains in the view/service.
- New `templates/appointments/technician_maintenance_completion.html`: render allowlisted fields, relevant part choices, CSRF token, and validation errors; no ORM queries/calculations in template.
- `apps/appointments/tests.py`: focused completion, rollback, authorization, and PostgreSQL concurrency coverage following current conventions.
- `.agents/plans/012-maintenance-completion-inventory.md`: record the human approval and validation report.

No model, migration, dependency, environment, AI, AgentActionLog, demo-data, or unrelated UI changes are planned. Existing relationships remain unchanged.

## Risks and Problems

- Implementing any transition outside the human-approved three edges would invent behavior and could alter an ineligible Appointment; all other transitions remain rejected.
- Appointment row locking serializes completion requests that use this service, but current schema allows multiple MaintenanceRecords per Appointment from other write paths.
- Inventory races require deterministic row-lock ordering and stock revalidation inside the transaction; insufficient stock for one part must roll back every write.
- Mileage lower than accepted prior mileage is explicitly an integrity concern and cannot be silently accepted or resolved by a Technician.
- Partial commits, form overposting, attacker-controlled relation IDs, or broad Appointment lookup could corrupt history or expose another Technician's/Owner's data.
- PostgreSQL availability determines whether transaction and concurrency guarantees can be validated; no SQLite substitution is acceptable.
- Parallel AgentActionLog work is excluded and must not be touched.

## Alternatives Considered

### Option A — Use the human-approved narrow transition mapping (selected)

Implement only PENDING -> IN_PROGRESS, CONFIRMED -> IN_PROGRESS, and IN_PROGRESS -> COMPLETED.

Advantages: resolves the SRS ambiguity through an explicit product decision and enables UJ-07 while keeping all other transitions unavailable.

Disadvantages: the transition mapping is a human decision, not a literal SRS rule.

### Option B — Infer additional transitions

Infer additional status changes from the enum or journey narrative.

Advantages: might offer more flexible status handling.

Disadvantages: exceeds the human decision and invents behavior. Rejected.

## Recommended Approach

Choose Option A. The human owner resolved the SRS ambiguity with three explicit edges. Implement only those edges and revalidate them under lock. Document the mapping as a human decision, not as literal SRS transition text.

## Implementation Steps

1. Implement explicit forms and the atomic, assigned-only completion domain service with deterministic SparePart locking.
2. Add the POST-only start-service operation and CSRF-protected completion form/POST route while preserving Technician assignment isolation.
3. Add focused authorization, field-derivation, status, duplicate, input-validation, stock, rollback, and PostgreSQL concurrency tests.
4. Run the prescribed checks in order, stop at the first real failure, review the complete diff, then mark IMPLEMENTED only if all gates pass.

## Test Plan

If implementation becomes approved, cover:

- Authorization: anonymous redirect; TECHNICIAN success; OWNER/ADMINISTRATOR 403; missing TechnicianProfile denial; foreign, unassigned, and nonexistent Appointment 404; no cross-object disclosure.
- HTTP/CSRF: GET has no writes; unsupported methods rejected; completion is POST-only; CSRF-less POST rejected; rendered token succeeds; forged relation/actor IDs do not influence saved relationships.
- Completion: approved source statuses accepted and all other statuses rejected; successful status is COMPLETED; exact derived Vehicle/ServiceType/Technician/Appointment; notes/mileage/date persistence; future and negative/lower-than-accepted mileage rejected; repeat completion safely rejected; unrelated Appointment fields preserved; failed completion leaves no MaintenanceRecord.
- Parts: one and multiple valid parts; duplicate/missing IDs, zero/negative/malformed quantities rejected; insufficient stock rejected; exact-stock succeeds; every part validates before writes; no client price/total/record ID authority.
- Atomicity: full rollback of status, MaintenanceRecord, MaintenancePart, and all inventory on any later failure; stock never negative; deterministic lock order.
- PostgreSQL concurrency: competing use of stock cannot overdraw; concurrent duplicate completion is serialized and at most one record is created through the approved service.
- Regression: Appointment booking and Owner Appointment tests; Administrator assignment and Technician list/detail tests; MaintenanceRecord/due-service tests; Inventory and Vehicle tests; complete PostgreSQL suite.
- Validation commands, in order: `python manage.py check`; `python manage.py makemigrations --check`; focused Plan 012 tests; `python manage.py test apps.maintenance.test_seed_demo_data -v 1`; `python manage.py test apps.appointments apps.maintenance apps.inventory apps.vehicles -v 1`; `python manage.py test -v 1`; `git diff --check`; migration-directory and complete-diff review. Use `.venv` and PostgreSQL. Stop at first real failure. If PostgreSQL is unavailable, do not claim test success or mark the plan IMPLEMENTED.

## Migration and Environment Impact

No Model or Migration changes are planned because current relationships support the required workflow. Current models allow multiple MaintenanceRecords per Appointment; service-level appointment locking and existing-record rejection are the planned duplicate guard. No dependency, environment variable, database, or setup changes. If discovery during implementation proves the schema cannot safely satisfy an approved requirement, stop and return this plan to blocked/pending review rather than silently changing schema.

## Security Analysis

- Enforce role, profile, and assignment on the backend for every request.
- Scope Appointment lookup before retrieving it; do not distinguish another Technician's appointment from a nonexistent one.
- Derive all relationships and actor identity from server-side objects; use explicit form fields only.
- Require CSRF-protected POST for all writes; GET remains read-only.
- Validate each quantity and every inventory row inside the locked transaction before writing.
- Use row locks and atomic rollback to protect stock invariants; never use raw SQL.
- Do not catch broad database errors or render stack traces or sensitive object details.
- No AgentActionLog or AI access is in scope.

## Rollback Strategy

The intended implementation adds no schema changes. Roll back by reverting only the Plan 012 application files and templates; no data migration reversal is required. Any partially attempted operation is contained by the transaction and must leave Appointment status, maintenance history, and stock unchanged. Do not roll back or modify concurrent Plan 013 work.

## Definition of Done

- The exact human-approved mapping is recorded here and is the only transition set implemented.
- FR-10 and UJ-07 completion behavior works with status COMPLETED and a derived MaintenanceRecord; FR-20 parts usage reduces inventory safely where supplied.
- Assignment authorization, explicit field allowlists, relationship derivation, date/mileage validation, duplicate protection, and non-negative stock are covered.
- Atomic transaction, deterministic locks, full rollback, and PostgreSQL concurrency behavior are verified.
- Focused and full PostgreSQL suites, Django check, migration check, whitespace check, and full diff review pass; exact results are reported.
- No unauthorized Model/Migration, AgentActionLog, AI, Demo Seed Data, or unrelated change exists.

## Open Questions

None blocking for the approved scope. The transition mapping is PENDING -> IN_PROGRESS, CONFIRMED -> IN_PROGRESS, and IN_PROGRESS -> COMPLETED. Service date is server-derived via `timezone.localdate()`; submitted mileage below `Vehicle.current_mileage` is rejected.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-27

## Implementation Report

- Summary: Implemented and validated Technician service start and maintenance completion. The mapping PENDING -> IN_PROGRESS, CONFIRMED -> IN_PROGRESS, and IN_PROGRESS -> COMPLETED is the human-approved resolution recorded for this plan; it is not literal SRS transition text. No other transition is implemented.
- Files created: `.agents/plans/012-maintenance-completion-inventory.md`; `templates/appointments/technician_maintenance_completion.html`.
- Files modified: `apps/appointments/forms.py`, `apps/appointments/services.py`, `apps/appointments/views.py`, `apps/appointments/urls.py`, `apps/appointments/tests.py`, and `templates/appointments/technician_appointment_detail.html`.
- Start-service behavior: TECHNICIAN-only, assigned-Appointment POST; locks and revalidates the Appointment; only PENDING or CONFIRMED may become IN_PROGRESS; changes no other Appointment fields. GET is read-only and CSRF is required.
- Completion eligibility: Only an assigned Appointment in IN_PROGRESS may complete. PENDING, CONFIRMED, COMPLETED, and CANCELLED cannot complete. The operation is POST-only; the authorized form GET does not mutate.
- Authorization and assignment isolation: anonymous users redirect to login; OWNER and ADMINISTRATOR are denied; a TechnicianProfile is required. Appointment resolution is scoped to the authenticated Technician, with foreign, unassigned, and nonexistent appointments returning 404. Client-supplied identity or relation IDs have no authority.
- MaintenanceRecord: Vehicle and ServiceType derive from the locked Appointment; Technician derives from the authenticated TechnicianProfile; Appointment derives from the authorized URL object. Service date is server-derived. Explicit mileage and notes fields are validated.
- Parts and inventory: zero or more Parts may be recorded. Part IDs resolve server-side; duplicates, missing Parts, malformed/non-positive quantities, and insufficient stock are rejected. All selected SpareParts are locked in deterministic primary-key order and stock is reduced only after every selection passes validation. Exact-stock use is supported; inventory cannot go negative.
- Transaction and rollback: completion runs in one `transaction.atomic()` block, locks and revalidates the assigned Appointment and selected SpareParts, creates the MaintenanceRecord and MaintenancePart rows, reduces stock, and sets COMPLETED before commit. Failure rolls back Appointment status, the MaintenanceRecord, all MaintenancePart rows, and every stock change.
- PR #18 Copilot finding (MEDIUM): direct service mileage coercion with `int()` could truncate fractional numeric inputs. The service now accepts Python integers and signed, decimal-free ASCII integer strings, explicitly rejects bool and all other numeric/text types that do not match that contract, and preserves `invalid_mileage` with the existing safe validation messages. It never rounds or truncates.
- Mileage regression coverage: direct-service tests reject `550.9`, `-0.5`, `True`, fractional `Decimal`, malformed text, and a negative integer; accept an integer and a decimal-free integer string; and verify every rejected input leaves status IN_PROGRESS, creates no MaintenanceRecord or MaintenancePart, and leaves stock unchanged. Existing HTTP `IntegerField` validation is unchanged.
- PR #18 Copilot finding (LOW): corrected the proposed template path to `templates/appointments/technician_maintenance_completion.html`, matching the actual created template.
- Tests executed (PostgreSQL): focused `TechnicianMaintenanceWorkflowTests` and `TechnicianCompletionConcurrencyTests` — 20/20 passed; Demo Seed Data — 4/4 passed; Appointments, Maintenance, Inventory, and Vehicles — 164/164 passed; complete suite — 229/229 passed.
- Validation: Django check passed; `makemigrations --check` reported no changes detected; `git diff --check` passed. Model and Migration inspection confirmed no changes.
- Concurrency: PostgreSQL concurrency coverage passed as part of the focused 20/20 and complete 229/229 results; concurrent completion persisted one record and consumed stock once.
- Parallel scope: No Plan 013 or AgentActionLog changes. Demo Seed Data files and behavior were not modified; seed tests passed.
- Deferred scope and remaining risks: Owner cancellation remains deferred because eligible cancellation statuses are unspecified. Every Appointment transition outside the three human-approved edges remains deferred. No known in-scope validation failure remains.
- Deviations from plan: The earlier missing test helpers were corrected only in `apps/appointments/tests.py`. The PR #18 mileage correction is confined to `apps/appointments/services.py` and its regression tests. No production changes were made for the helper correction.
