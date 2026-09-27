# Plan: Technician Appointment Workflow

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/technician-appointment-workflow
- Created: 2026-09-27
- Last updated: 2026-09-27

## Objective

Implement an authenticated Technician's assigned Appointment list and detail pages. Evaluate the SRS status-update requirement against the existing status model and implement only a transition policy explicitly established by the authoritative SRS. Do not infer missing transition rules.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`.

- FR-16: Technicians view only appointments assigned to them; unrelated appointments are inaccessible.
- FR-17: Technicians may update the status of assigned appointments and only valid transitions are accepted. The SRS does not define an exact transition graph.
- SRS §4.1 authorization rule: technician appointment access is filtered by `technician__user=request.user`.
- SRS §4.2 role matrix: the Technician may read/update assigned appointments; Owners are denied.
- UJ-07 describes a Technician opening an assigned appointment, starting service, recording notes and parts, marking it completed, and creating a maintenance record. It does not define allowed source statuses or a complete transition graph.

## Current-State Analysis

- `Appointment` already stores a nullable `technician`, status choices `PENDING`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`, and model ordering `-created_at, -id`.
- `TechnicianProfile` is a one-to-one relation to User and is associated with the `TECHNICIAN` role by model validation. The profile can be absent for a TECHNICIAN user created outside the normal profile workflow.
- Appointment booking and Administrator initial assignment are implemented. Owner Appointment list/detail are implemented and must remain unchanged in behavior.
- Existing authorization uses `LoginRequiredMixin` before `UserPassesTestMixin`; role-specific data access is enforced in the queryset.
- FR-17 says only valid transitions are accepted, but neither FR-17 nor UJ-07 specifies a complete transition graph or the source statuses from which service may start. Implementing completion alone would also skip the maintenance-record behavior in UJ-07, which is outside this appointment read slice.

## Proposed Changes

- `apps/appointments/views.py`: add Technician-only list/detail views. Require an existing TechnicianProfile, scope both querysets to it, and select related vehicle, service type, and slot.
- `apps/appointments/urls.py`: add named Technician list/detail routes without changing existing routes.
- `templates/base.html`: show a Technician appointments link only for TECHNICIAN users.
- `templates/appointments/technician_appointment_list.html` (create): display assigned appointment vehicle, service, slot, status, and a clear empty state.
- `templates/appointments/technician_appointment_detail.html` (create): display only assignment-relevant appointment and vehicle information, status, safe notes, and creation time.
- `apps/appointments/tests.py`: add focused tests for login, role authorization, missing profile, assigned-only list/detail visibility, ordering, empty state, safe rendering, read-only behavior, and bounded related-object loading.
- Do not modify forms, services, models, or migrations. No status mutation is added because the allowed transition policy is unresolved.

## Risks and Problems

- A broad Appointment lookup could expose another Technician's or an unassigned Appointment. Resolve details only within a queryset filtered by the authenticated user's TechnicianProfile; return 404 for foreign, unassigned, and nonexistent IDs.
- A role check alone is insufficient if a TECHNICIAN account has no profile. Reject that account safely before querying assignments.
- Displaying Owner/User details could disclose unnecessary data. Render only the vehicle details and appointment fields needed by the Technician workflow; rely on template autoescaping for notes.
- FR-17 requires status updates but provides no exact graph. Guessing predecessors, allowing arbitrary model choices, or completing without the rest of UJ-07 would be unsafe. Defer all status mutation until an authoritative transition policy is available; list/detail remains independently useful.
- This slice is read-only, so CSRF tokens, write transactions, and row locks are not applicable. GET must not mutate; POST remains unsupported.

## Alternatives Considered

### Option A — Assigned list/detail and defer status mutation (recommended)

Implement the unambiguous FR-16 read workflow and keep status data visible without changing it.

Advantages: enforces assignment isolation, delivers the complete read-only slice, and avoids making up status rules or partially implementing the UJ-07 completion flow.

Disadvantages: FR-17 remains incomplete pending a transition-policy decision.

### Option B — Infer transitions from stored choices or UJ-07 wording

Allow one or more transitions based on the status enum or narrative sequence.

Advantages: adds a status control in this plan.

Disadvantages: the enum defines stored values, not permitted edges; UJ-07 does not define source-state eligibility and couples completion to maintenance record creation. This would invent behavior and risk inconsistent records. Rejected.

## Recommended Approach

Choose Option A. Implement assigned-only Technician list and detail endpoints with role and profile checks. Display current status, but do not expose mutation controls or change status. Record the unresolved transition-policy question for a separate authoritative decision.

## Implementation Steps

1. Add the approved Plan 011 file.
2. Implement Technician authorization, profile resolution, assigned querysets, URLs, templates, and navigation.
3. Add focused regression tests without changing prior tests.
4. Run requested PostgreSQL validation in order, stopping at the first real failure; inspect the complete diff and migration boundary.
5. Mark the plan IMPLEMENTED only if all validation gates pass. If PostgreSQL is unavailable, keep this plan APPROVED and report exact commands needed.

## Test Plan

- Anonymous list/detail requests redirect to login.
- TECHNICIAN with a profile can access their assigned list and detail.
- OWNER and ADMINISTRATOR receive 403.
- TECHNICIAN without a TechnicianProfile is rejected safely.
- List contains only the current Technician's assigned Appointments, excludes unassigned and other-Technician Appointments, preserves `Appointment` model ordering, and renders an empty state.
- Detail resolves only within the current Technician's assigned queryset; another Technician's, unassigned, and nonexistent Appointments return 404.
- Detail renders only relevant vehicle and appointment data, including optional notes safely, without Owner email or unrelated User/role data.
- GET does not mutate; POST to read-only endpoints is rejected.
- Queryset related-object loading remains bounded through `select_related`.
- Existing Plan 007 booking, Plan 008 Owner Appointment, and Plan 009 Administrator assignment regressions pass through the requested suites.

## Migration and Environment Impact

No model, migration, dependency, settings, or environment changes. Validation uses the configured PostgreSQL database and repository virtual environment. The implemented slice is read-only and needs no write transaction or lock.

## Open Questions

None blocking for the implemented list/detail scope. FR-17 transition edges, source-state eligibility, and the relationship between completion and MaintenanceRecord creation remain deferred until specified by an authoritative requirement or decision.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-27

## Implementation Report

- Summary: Implemented and validated the assigned-only Technician Appointment list and detail pages. Status mutation remains deferred because FR-17 defines no exact transition graph. MaintenanceRecord creation and parts usage are also deferred.
- Files created: `.agents/plans/011-technician-appointment-workflow.md`, `templates/appointments/technician_appointment_list.html`, and `templates/appointments/technician_appointment_detail.html`.
- Files modified: `apps/appointments/views.py`, `apps/appointments/urls.py`, `apps/appointments/tests.py`, and `templates/base.html`.
- Tests executed on PostgreSQL (verified results supplied): `.venv/bin/python manage.py test apps.appointments.tests.TechnicianAppointmentViewTests -v 1` — **10/10 passed**; `.venv/bin/python manage.py test apps.appointments apps.vehicles -v 1` — **99/99 passed**; `.venv/bin/python manage.py test -v 1` — **205/205 passed**; `.venv/bin/python manage.py check` — passed; `.venv/bin/python manage.py makemigrations --check` — no changes detected; `git diff --check` — passed.
- Test results: TechnicianAppointmentViewTests: 10/10 passed. Appointments and Vehicles: 99/99 passed. Complete PostgreSQL suite: 205/205 passed. Django check passed. Migration check reported no changes detected. Whitespace check passed.
- Migration/environment changes: No Model or Migration changes. No settings, dependencies, or environment changes.
- Security checks: Anonymous users redirect to login. Endpoints require the TECHNICIAN role and an existing TechnicianProfile; OWNER and ADMINISTRATOR receive 403, and a Technician without a profile receives 403. List and detail querysets are scoped to the authenticated TechnicianProfile. Other-Technician, unassigned, and nonexistent Appointment details return 404. The list queryset uses `select_related` for vehicle, service type, and slot; detail rendering shows only relevant appointment and vehicle information, escapes notes safely, and avoids Owner identity data. These behaviors are covered by the passing focused tests. The endpoints are read-only; POST is unsupported and GET does not mutate. CSRF enforcement and write transactions/locking are not applicable because no mutation endpoint was implemented.
- Remaining risks: FR-17 status transition policy remains deferred because it defines no exact transition graph. MaintenanceRecord creation and parts usage are deferred.
- Deviations from plan: None. Status mutation and completion-related work remain deferred as documented.
