# Plan: Owner Slot Discovery + Manual Appointment Booking

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: TBD
- Reviewer: TBD
- Branch: `feature/owner-slot-discovery-manual-booking`
- Created: 2026-09-26
- Last updated: 2026-09-27

## Goal

Allow an authenticated Owner to see active future service slots with remaining capacity, select one of their own vehicles and an existing service type, and submit a manual appointment booking. The server must revalidate ownership and availability and create the appointment atomically, including protection against concurrent bookings. This is a normal Django workflow; it does not invoke AI.

## Scope

- Present existing `ServiceType` records as selectable services. The current model has no active/inactive field, so this plan does not invent one or filter on one.
- Show all `ServiceSlot` records that are active, have `start_time > timezone.now()`, and have fewer active appointments than `capacity`. Do not impose an arbitrary date horizon or pagination in this initial implementation unless an existing project constraint requires it.
- Let an Owner choose a vehicle from only their own vehicles, an existing service type, and an available slot.
- Validate the submitted values on the server and create an `Appointment` with the model's default `PENDING` status, `booked_by_agent=False`, and no technician assignment.
- Keep the displayed availability advisory: recheck all booking conditions at submission time and return a clear safe error if the slot became unavailable.
- Keep the operation inside the existing appointment domain and use the existing `ServiceSlot` and `Appointment` models unless implementation discovery identifies a concrete SRS-required gap. Any such schema change requires stopping and revising this plan before implementation.

## Out of Scope

- AI tools, chatbot, agent confirmation tokens, LLM integration, and AI booking.
- Technician or Administrator workflows, technician assignment, appointment status transitions, and dashboards.
- Appointment cancellation or rescheduling. SRS FR-15 is **Should**, and neither cancellation nor rescheduling is an inseparable dependency of FR-12–14 booking. They require a separate plan and authorization rules.
- Slot-to-service or slot-to-technician relations. The authoritative SRS and current model do not define either relation. A slot is available for any selected existing service type; the appointment's technician remains nullable for later assignment.
- Service-type activation/availability flags, capacity stored on another model, notifications, or other unapproved schema/features.

## SRS References

Authoritative source: `docs/CARVIX_SRS_Group6.docx`, Document Version 1.0, Initial Approved Baseline.

- §2 FR-12 (Must): Owners view active service slots; only active slots with remaining capacity are displayed.
- §2 FR-13 (Must): Owners manually book appointments for their own vehicles; a valid appointment is stored against the selected slot.
- §2 FR-14 (Must): Unavailable, full, expired, or duplicate slots produce a clear error and no appointment.
- §2 FR-30 (Must): Appointment booking is atomic; failures leave no partial booking data.
- §3 NFR-S01–S04: private endpoints require authentication, state-changing requests use CSRF, owner access is constrained by `request.user`, and role checks prevent privilege escalation.
- §3 NFR-R01: multi-write booking operations use atomic transactions.
- §3 NFR-D02–D04: valid slot time range, slot capacity is not exceeded, and relationships preserve valid history.
- §4 RBAC matrix and §4.1: Owners may access their own appointments; use backend role checks and owner-filtered querysets before retrieving objects.
- §6.2: `ServiceSlot` fields are `start_time`, `end_time`, `capacity`, `is_active`; `Appointment` has vehicle, service type, slot, nullable technician, status, notes, `booked_by_agent`, and `created_at`.
- §6.3: capacity is checked inside an atomic transaction; an active slot cannot exceed configured capacity.
- §7 UJ-04: owner selects own vehicle and maintenance type, views active slots, selects a slot, server revalidates availability, then creates the appointment.
- §7 UJ-09: a slot made unavailable after display is rechecked during booking and rejected without overbooking or partial writes.
- §9.5: complete the normal application workflow before AI; implement and test confirmed AI booking only after manual booking works.

## Existing Repository Dependencies and Current-State Analysis

- `apps/appointments/models.py` defines `ServiceSlot(start_time, end_time, capacity, is_active)` with `start_time` ordering, end-after-start and positive-capacity constraints, and indexes on start time and active/start time.
- The same file defines `Appointment(vehicle, service_type, slot, technician, status, notes, booked_by_agent, created_at)`. `technician` is nullable; status defaults to `PENDING`; `booked_by_agent` defaults to `False`.
- `ACTIVE_APPOINTMENT_STATUSES` is the current definition of capacity-consuming and duplicate-blocking bookings: `PENDING`, `CONFIRMED`, and `IN_PROGRESS`. `COMPLETED` and `CANCELLED` are terminal and do not consume capacity under this definition.
- The database partial unique constraint `appointments_active_slot_vehicle_uniq` prevents an active appointment for the same `(slot, vehicle)`. It does **not** enforce total slot capacity.
- `apps/maintenance/models.py` defines `ServiceType` with `name`, `description`, `interval_km`, `interval_months`, `duration_minutes`, and `price`. It has no `is_active` field. `apps/vehicles/models.py` defines vehicle ownership through `Vehicle.owner`.
- `apps/appointments/admin.py` registers slots and appointments in Django Admin. There are currently no appointment forms, booking services/selectors, owner booking views, appointment URLs, booking templates, or appointment workflow tests.
- `apps/vehicles/views.py` contains an `OwnerRequiredMixin`, filters vehicle lists by `owner=request.user`, and uses owner-scoped detail/update querysets. The owned Vehicle Detail page is the primary Owner booking entry point. The plan should use the same role and ownership principles without assuming a shared permission framework exists.
- `config/urls.py` includes authentication and vehicle URLs but not appointment URLs. Existing templates are Django templates under `templates/`; `templates/base.html` is the shared layout. Existing vehicle detail is owner-scoped and already presents maintenance context.
- `docs/architecture.md` and `docs/user-journeys.md` are supporting material and contain details not represented by current models. Where they differ from the DOCX SRS or repository schema, the SRS and actual model fields govern. In particular, do not add a technician or service relation to `ServiceSlot` based on supporting-document diagrams.
- Approved Plan 000 places normal workflows before AI. Implemented Plan 004 created the domain schema and explicitly deferred transactional slot-capacity enforcement. Implemented Plans 005–006 provide owner vehicle management and maintenance overview but do not implement appointment booking.

## Proposed Changes and Responsibilities

Expected files, subject to implementation inspection after approval:

- `apps/appointments/selectors.py` (create): read-only query for active future slots annotated with a count of active appointments; expose only slots whose active count is below `capacity`. Use the model's `ACTIVE_APPOINTMENT_STATUSES`; avoid per-slot count queries.
- `apps/appointments/services.py` (create): booking use case. Accept the authenticated actor and validated vehicle/service/slot identifiers (never a model-supplied user ID); re-fetch and authorize the vehicle, serialize booking attempts on the selected slot, recheck availability and duplicate rules, create the appointment atomically, and return a domain result suitable for safe form feedback. Translate the database uniqueness race into a stable booking conflict outside a broken transaction.
- `apps/appointments/forms.py` (create): validate the selected vehicle against `Vehicle.objects.filter(owner=request.user)`, validate service and slot identifiers, and return field-specific validation errors. A slot shown on GET is not trusted on POST; the service rechecks current availability. Do not accept owner, technician, status, `booked_by_agent`, or other protected model fields from the browser.
- `apps/appointments/views.py` (create): require login and Owner role for both discovery and POST; render the booking flow, bind server-side actor identity, invoke the form and booking service, and render success or safe conflict/validation feedback. Never retrieve a submitted vehicle globally before applying owner scope.
- `apps/appointments/urls.py` (create): namespaced routes for slot discovery/booking, with a stable appointment identifier only if needed for the success page. Do not add cancellation routes.
- `config/urls.py` (modify): include the appointments URLconf.
- `templates/appointments/slot_list.html` and `templates/appointments/booking_form.html` (create) or one combined template if the selected UX remains clear: show service, owner vehicle, eligible future slots, capacity-independent safe display information, empty state, validation errors, and booking success/conflict feedback. Never present stale availability as guaranteed.
- `templates/vehicles/vehicle_detail.html` (modify): add the primary booking entry point on the owned Vehicle Detail page, without treating the link as authorization.
- `apps/appointments/tests.py` (modify): add selector, form, view authorization, successful booking, and PostgreSQL transaction/concurrency coverage while preserving existing model tests.
- `docs/user-journeys.md` (modify if its current UJ-04 flow needs to reflect implemented route behavior): align supporting documentation with SRS and implementation; do not treat it as authority over SRS.

No source file or schema is changed by this DRAFT plan. No migration is expected: the current models contain the required relationships and capacity/status fields. If implementation proves otherwise, stop and return with the evidence and a revised plan before changing models or migrations.

## Backend Authorization Rules

- Require an authenticated session and the CARVIX `OWNER` role on every discovery and booking endpoint; hidden navigation or form controls are not authorization.
- Derive the actor exclusively from `request.user`; never accept `user_id` or owner identity from submitted fields.
- Scope the vehicle queryset to `owner=request.user` before resolving a posted vehicle ID. A foreign-owned or missing vehicle must not be booked; return a safe denial/validation response without leaking object details.
- Validate that the selected `ServiceType` exists. The current schema has no active flag, so do not invent an active-service filter.
- Resolve the slot again server-side and require `is_active=True` and `start_time > timezone.now()` at booking time. A slot that has already started is not bookable even when its `end_time` is still in the future.
- Count only `ACTIVE_APPOINTMENT_STATUSES` against slot capacity. Reject if the count is at or above capacity.
- Reject a duplicate active appointment for the same vehicle and slot. Keep the database partial unique constraint as final defense even when the service prechecks.
- Assign `status`, `technician`, and `booked_by_agent` server-side using the current model defaults/ordinary booking values (`PENDING`, `None`, `False`). Do not permit mass assignment of these values.
- Use POST with Django CSRF protection for booking. GET requests remain read-only.

## Validation Rules

- Missing, malformed, unknown, or tampered vehicle/service/slot identifiers produce safe field-specific errors and no write.
- Vehicle must belong to `request.user`; validate through a request-scoped queryset and recheck in the booking service.
- Service must be an existing `ServiceType`; the SRS does not require a slot/service association.
- Slot must exist, be active, and have `start_time > timezone.now()` at commit-time validation. A slot that has started, is full, or was taken after display is unavailable, even if its `end_time` is still in the future.
- Remaining capacity is `capacity - count(appointments with status in ACTIVE_APPOINTMENT_STATUSES)` and must be greater than zero.
- No existing appointment for the same vehicle and slot may have an active status. Terminal appointments do not block a new booking under the existing constraint.
- Successful booking uses the existing nullable technician field with `None`; it does not infer a technician from a slot.
- Error messages are sanitized, actionable, and do not include stack traces or another owner's data.

## Transaction and Concurrency Strategy

- Use `transaction.atomic()` for the booking operation.
- On PostgreSQL, lock the selected `ServiceSlot` row with `select_for_update()` inside the transaction before reading capacity-consuming appointment count. Every booking path must acquire that same slot lock before counting and creating, so concurrent bookings for that slot serialize. Do not rely on a count-then-insert without a lock.
- After obtaining the lock, re-read slot active/future state, count active bookings, check the same-vehicle duplicate, and create the appointment in the same transaction.
- Retain `appointments_active_slot_vehicle_uniq` as defense in depth. If a uniqueness race or `IntegrityError` occurs, allow the atomic block to roll back and translate the conflict after the transaction has exited; do not query inside a broken transaction.
- Test the concurrency guarantee using PostgreSQL and independent transactions/connections. SQLite is not an acceptable substitute for row-lock behavior. If the PostgreSQL test environment cannot exercise this guarantee, document the limitation and do not claim concurrency safety is verified.

## Template / UI Flow

1. Owner opens the booking flow from the owned Vehicle Detail page.
2. Page offers that Owner's vehicle, one existing service type, and all active slots with `start_time > timezone.now()` and remaining capacity, without an arbitrary date limit or pagination in the initial implementation. It shows a useful empty state when no slots qualify.
3. Owner submits the selection via a CSRF-protected POST.
4. On invalid input or a stale/full slot, show a clear error and allow the Owner to refresh/reselect; do not claim an appointment was created.
5. On success, show a confirmation based only on the saved appointment and its returned slot/service/vehicle data. Do not promise a technician assignment.

## Tests and Acceptance Criteria

Plan-only; do not run tests before approval. After approval, tests should cover:

- Selector returns only active future slots with available capacity; excludes inactive, past/started, full slots; counts `PENDING`, `CONFIRMED`, and `IN_PROGRESS`; does not count `COMPLETED` or `CANCELLED`.
- Authenticated Owner can select their own vehicle, existing service, and eligible slot; successful POST creates exactly one `PENDING` appointment linked to those objects with `technician=None` and `booked_by_agent=False`.
- Anonymous requests cannot access discovery or booking; non-Owner roles are denied.
- Another Owner's vehicle ID, missing vehicle/service/slot, invalid IDs, inactive/expired/full slot, and duplicate active `(vehicle, slot)` are rejected with no appointment created and no cross-owner data disclosed.
- Slot becoming full, inactive, or expired between display and POST is rejected after service revalidation.
- Completed/cancelled appointment history does not cause the active duplicate rule to reject an otherwise-valid booking.
- CSRF protection remains active on the state-changing route; success and failure feedback are rendered safely.
- PostgreSQL database uniqueness and transaction/concurrency behavior: concurrent requests cannot exceed slot capacity; a competing request receives a stable conflict result; rollback leaves no partial booking.
- Regression coverage preserves existing appointment model constraints and existing vehicle ownership behavior.

Acceptance criteria:

1. An Owner sees only active future slots with remaining capacity and can choose an existing service type and only their own vehicle.
2. The server independently revalidates role, ownership, service/slot existence, active/future state, capacity, and duplicate status on submission.
3. A valid submission creates one ordinary manual `PENDING` appointment with `booked_by_agent=False`; no technician is inferred or assigned.
4. Invalid, unauthorized, stale, full, expired, duplicate, and concurrent submissions create no extra or partial booking and return safe actionable feedback.
5. Capacity is not exceeded under concurrent booking attempts on the supported PostgreSQL backend.
6. No slot-service or slot-technician relationship, AI flow, cancellation flow, or unrelated workflow is added.

## Risks

- A read-time slot list can become stale; only the transactional POST recheck determines whether booking succeeds.
- The existing partial unique constraint prevents same-vehicle duplicate active bookings but cannot cap total active bookings. The per-slot row lock is essential and every booking writer must follow the same lock ordering.
- PostgreSQL row-lock semantics cannot be proven with non-PostgreSQL tests; use the configured PostgreSQL test environment for concurrency coverage.
- Role and object checks can be bypassed if enforced only in the UI or only in the form; duplicate them at the service boundary.
- The service catalog has no active flag; adding one or guessing which services to hide would require a separate approved requirement/schema decision.
- Supporting architecture and journey documents include concepts not present in the SRS/current models. Do not implement those assumptions as part of this plan.
- Appointment cancellation (FR-15, Should) has separate eligibility and ownership behavior and is not needed to create or safely validate bookings.

## Alternatives Considered

### Option A — Add a focused appointment workflow using the current models (recommended)

Add read-only selectors, request-scoped forms/views, and an atomic booking service. Serialize on the existing ServiceSlot row and rely on the existing partial unique constraint for duplicate defense. This directly implements FR-12–14 and FR-30 without expanding the schema or involving AI.

Advantages: matches SRS fields and Plan 000 sequencing; smallest coherent user-facing workflow; keeps authority and concurrency control in Django; creates reusable domain logic for later tools.

Disadvantages: relies on all writers following the slot-lock protocol; slot availability may change after GET and must be handled as a normal booking conflict.

### Option B — Introduce booking-related schema or broader staff workflows first

Add service/technician relations to slots, status lifecycle, or technician/admin work before owner booking.

Advantages: could support richer scheduling/staff operations if the SRS required them.

Disadvantages: current SRS and model do not require slot-to-service or slot-to-technician relations; broadens scope, creates migration and authorization work, and is not needed for the SRS owner booking acceptance criteria. Not recommended absent new authoritative evidence.

## Recommended Approach

Choose Option A. Existing `ServiceSlot` and `Appointment` fields represent the SRS booking relationships, and Plan 004 deliberately deferred transactional capacity enforcement to workflow logic. A focused selector/form/view/service slice is the next normal workflow before AI integration. Keep any newly discovered schema necessity as a blocking conflict for plan review rather than silently changing the model.

## Implementation Steps

1. After approval, inspect current files and implement an active/future/remaining-capacity selector using the current active status constant.
2. Add a request-scoped booking form and Owner-protected views/routes; connect them to a clear template flow and existing navigation.
3. Implement the atomic booking service with slot row locking, in-transaction rechecks, server-controlled appointment fields, and safe duplicate/capacity conflict handling.
4. Add positive, invalid-input, role, ownership, stale-slot, capacity, duplicate, CSRF, rollback, and PostgreSQL concurrency tests.
5. Update supporting journey documentation only where needed to reflect the SRS-compliant implemented flow.
6. Run the relevant focused tests and full project suite on PostgreSQL per AGENTS.md, then report exact commands/results and migration/environment impact. Do not mark this plan IMPLEMENTED before required tests and review are complete.

## Definition of Done

- This plan has been approved before implementation begins.
- The Owner journey meets all acceptance criteria and FR-12–14; atomicity meets FR-30/NFR-R01 and capacity integrity meets NFR-D03.
- Backend authentication, Owner role, ownership, input validation, CSRF, stale-state checks, and safe errors are covered by tests.
- PostgreSQL concurrency tests show that slot capacity is not exceeded; rollback and uniqueness behavior are verified.
- Existing models/migrations are reused, with no schema change unless a documented SRS conflict is first brought back for plan revision.
- Existing tests remain intact; focused and full test suites pass on PostgreSQL, with exact results reported.
- Supporting documentation is accurate where changed; no AI, cancellation, technician/admin, or unrelated workflow is added.
- No secrets/private data are added; environment/dependency impact is reported.
- A reviewer can reproduce the Owner booking flow and explain its authorization and transaction behavior.

## Open Questions

Resolved decisions:

1. The owned Vehicle Detail page is the primary Owner booking entry point.
2. Show all qualifying future slots without an arbitrary date limit or pagination in the initial implementation, unless existing project constraints require otherwise.
3. A slot is bookable only when `start_time > timezone.now()`; a slot that has already started is unavailable even if it has not ended.

No model/schema or service-to-slot/technician relationship decision is assumed. These decisions resolve the open questions; implementation still must not begin until separately authorized by the applicable workflow.

## Approval

- Decision: APPROVED
- Approved by: User
- Approval date: 2026-09-27

Implementation must not begin while Status is `DRAFT` or Decision is `PENDING`.

## Implementation Report

### Implementation Summary

Implemented Owner slot discovery and single-step manual appointment booking using the existing `ServiceSlot`, `Appointment`, `Vehicle`, and `ServiceType` models. The Owner starts from their owned Vehicle Detail page, selects an existing service and an eligible slot, and explicitly confirms booking in a CSRF-protected POST. The response confirms only the Appointment saved by the booking service.

### Files Created

- `apps/appointments/selectors.py`
- `apps/appointments/services.py`
- `apps/appointments/forms.py`
- `apps/appointments/views.py`
- `apps/appointments/urls.py`
- `templates/appointments/booking_form.html`

### Files Modified

- `config/urls.py`
- `templates/vehicles/vehicle_detail.html`
- `apps/appointments/tests.py`

### Authorization, Eligibility, and Booking Behavior

- Booking endpoints require authentication and the `OWNER` role. Anonymous users are redirected to login; authenticated non-Owners, including Technicians and Administrators, receive 403.
- Vehicle lookup is scoped to `request.user`; cross-owner vehicle IDs return 404. The service independently re-fetches and authorizes the Vehicle. The actor comes from authenticated request context; owner/user identity is not accepted from client fields.
- The selector returns active slots with `start_time > timezone.now()` and remaining capacity. Capacity counts only `ACTIVE_APPOINTMENT_STATUSES` (`PENDING`, `CONFIRMED`, `IN_PROGRESS`); full slots are excluded. Results use the model ordering by start time and primary key. A filtered aggregate annotates capacity in a bounded queryset; the selector test verifies one query and no per-slot count queries.
- The booking form allowlists Vehicle, ServiceType, and ServiceSlot selections. ServiceType records are drawn from the existing model without an invented activation field. The service re-fetches selections and rechecks slot activity, strict future start time, duplicate active booking, and capacity.
- Successful manual booking creates a `PENDING` Appointment with `technician=None` and `booked_by_agent=False`. Templates state that submission creates the Appointment and label the final action “Confirm and Book Appointment.” GET remains read-only; CSRF is enforced on POST.

### Transaction, Concurrency, and Error Handling

- Booking runs in `transaction.atomic()` and acquires `select_for_update()` on the ServiceSlot before revalidating capacity. Capacity is recounted inside the transaction after locking.
- Duplicate active booking is checked in the service and protected by the existing `appointments_active_slot_vehicle_uniq` constraint. Only an `IntegrityError` identifying that exact constraint is translated to a safe booking conflict after rollback; unrelated integrity errors propagate after rollback. Tests verify both paths and that no Appointment remains after rollback.
- PostgreSQL concurrency coverage uses independent worker connections/transactions and distinct Vehicles against a capacity-one slot. The test passed and confirmed the final active Appointment count does not exceed capacity.

### Validation Results

- Correction tests: **4/4 passed**.
- Targeted Plan 007 tests: **21/21 passed**.
- Appointments and Vehicles suites: **71/71 passed**.
- Complete project suite: **177/177 passed**.
- PostgreSQL concurrency test: **passed**.
- Django system check: **passed**.
- `makemigrations --check`: **no changes detected**.
- `git diff --check`: **passed, exit code 0**.
- Models and migrations: **no changes**.

### Deviations and Deferred Scope

- No schema change was needed. Supporting journey documentation was not modified; the implemented flow is described here and the authoritative SRS remains unchanged.
- Deferred scope: Owner appointment list, detail, and cancellation; Technician assignment and workflow; maintenance completion; inventory mutation; general RBAC; dashboards; `AgentActionLog`; AI tools; Chat UI; and LLM integration.
