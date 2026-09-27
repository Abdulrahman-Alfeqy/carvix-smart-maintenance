# Plan: Owner Appointment Management

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/owner-appointment-management
- Created: 2026-09-27
- Last updated: 2026-09-27

## Objective

Implement an authenticated Owner's appointment list and appointment detail pages, showing only appointments whose related vehicle belongs to that Owner. Cancellation is explicitly deferred until cancellable statuses are specified by an authoritative requirement or decision.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`, SRS FR-15 and its acceptance text: “The system shall allow owners to view and cancel eligible appointments belonging to them”; “Only cancellable statuses may be changed.” This plan implements the viewing portion only. FR-15 does not name cancellable statuses. The existing stored statuses (`PENDING`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED`) do not define cancellation eligibility, so this plan does not infer or implement it. The existing Appointment-to-Vehicle relationship and Owner Vehicle authorization conventions support the required ownership boundary.

## Current-State Analysis

- `apps/appointments/models.py` defines `Appointment` with `vehicle`, `service_type`, `slot`, `status`, and timestamps; ordering is newest first by `-created_at, -id`. Owner identity derives through `appointment.vehicle.owner`; there is no Appointment owner field.
- `apps/appointments/views.py` currently contains the booking view only. `apps/appointments/urls.py` exposes only the booking route.
- `apps/vehicles/views.py` provides `OwnerRequiredMixin`, Owner-only role checks, login redirects, and Owner-scoped querysets for vehicle list/detail.
- Appointment booking templates and tests are in `templates/appointments/` and `apps/appointments/tests.py`. Project URLs already include the appointments URLconf, and the base template has an Owner-only navigation location.
- Plan 004 records FR-15 while deferring cancellation eligibility and workflow. Plan 007 deferred the appointment list, detail, and cancellation as future workflow work.
- Branch and baseline match the request: `feature/owner-appointment-management`, `f4f810c`.

## Proposed Changes

- `apps/appointments/views.py`: add login-protected, Owner-role-protected list and detail views. Filter all appointments through `vehicle__owner=request.user`; use `select_related` for vehicle, service type, and slot. Keep generic detail lookup within the Owner-scoped queryset so cross-owner IDs return 404.
- `apps/appointments/urls.py`: add named list and detail routes while preserving the booking route.
- `templates/appointments/appointment_list.html` (create): show each Owner-scoped appointment's service, vehicle, scheduled slot, status, and detail link; include an empty state.
- `templates/appointments/appointment_detail.html` (create): show the same appointment's relevant vehicle, service, slot, status, and available appointment notes; link back to the list. Do not add cancellation controls.
- `templates/base.html`: add an Owner-only “Appointments” navigation link.
- `apps/appointments/tests.py`: add focused list/detail authorization, ownership, ordering, read-only behavior, and response privacy tests. Preserve all existing booking tests.

## Scope

- Owner Appointment List, including all of the Owner's appointments across statuses, ordered by the existing model ordering.
- Owner Appointment Detail, retrieved only through an Owner-scoped queryset.
- Anonymous users redirect to login. Authenticated TECHNICIAN and ADMINISTRATOR users receive 403 on these Owner endpoints. Cross-owner appointment identifiers return 404.
- GET is read-only. No mutation endpoint is introduced.
- Ownership is always derived from `Appointment.vehicle.owner`; no client-supplied Owner identity is trusted.

## Out of Scope

Appointment cancellation, cancellation eligibility/status transitions, rescheduling, technician assignment/workflows, maintenance completion, inventory, dashboards, generic RBAC, administrator UI, AgentActionLog, AI tools, Chat UI, LLM integration, model changes, migrations, dependencies, and unrelated redesign.

## Authorization and Data Handling

- Apply the existing `LoginRequiredMixin` before `OwnerRequiredMixin` so anonymous users redirect and authenticated non-Owners receive 403.
- The list queryset is filtered by `vehicle__owner=request.user`.
- The detail queryset is filtered by `vehicle__owner=request.user` before resolving the URL identifier. A missing or cross-owner identifier returns 404 with no appointment data disclosed.
- Do not accept Owner or Appointment identity from query/form payloads. URL appointment IDs identify a record only within the already scoped queryset.
- The views accept GET only. POST is rejected by Django's generic view handling; GET never changes status or any other record field.
- CSRF is not applicable to this read-only slice because it adds no state-changing request. If cancellation is planned later, that plan must define eligibility from an authoritative source and use a confirmed, CSRF-protected POST with server-side revalidation.

## Cancellation Decision

Cancellation is deferred. FR-15 says that only cancellable statuses may be changed but does not list those statuses. Existing status values are storage vocabulary, not an eligibility policy. No status set, transition, cancellation control, or cancellation endpoint is invented in this plan. Cancellation must receive a separate approved plan after the eligibility rule is established.

## Transaction and Schema Decision

List and detail are read-only, single-request database reads; `transaction.atomic()` is not justified. Existing relations and fields are sufficient. No Model or Migration changes are needed or permitted for this scope.

## Risks and Problems

- The primary risk is cross-owner disclosure through an unscoped detail lookup; both views must scope the queryset by `vehicle__owner=request.user`, and tests must verify 404 and lack of private content.
- Reusing the Owner role convention is necessary to prevent staff roles from using Owner endpoints; tests cover both TECHNICIAN and ADMINISTRATOR denial.
- Appointment status meaning may evolve, but list/detail display stored status labels without inferring transitions or eligibility.
- No mutation path exists, so CSRF and transactional write concerns do not apply. Existing Plan 007 booking behavior must remain passing.

## Alternatives Considered

### Option A — Implement list and detail, defer cancellation (recommended)

Add only the read-only Owner views required by FR-15's viewing clause, and defer cancellation until its eligibility rule is authoritative.

Advantages: implements the unambiguous part of the requirement, preserves history and existing statuses, and avoids inventing business rules.

Disadvantages: the complete FR-15 cancellation workflow remains outstanding.

### Option B — Implement list, detail, and choose a cancellation status set

Advantages: delivers more of FR-15 in one slice.

Disadvantages: the SRS and approved plans do not define the eligible statuses; selecting them would invent a business rule and violate the source-of-truth constraint. Rejected.

## Recommended Approach

Choose Option A. Implement Owner-scoped list and detail pages using the existing model and authorization conventions. Keep cancellation explicitly deferred until a source-authorized status eligibility rule exists.

## Implementation Steps

Implement the Owner-scoped list and detail views, routes, templates, and navigation together; add the focused tests; run validation gates in the requested order and stop on the first failure.

## Test Plan

- Anonymous list and detail requests redirect to the login page.
- OWNER can access the list and own appointment details.
- TECHNICIAN and ADMINISTRATOR receive 403 on both Owner endpoints.
- The list includes only the current Owner's appointments and follows model ordering.
- Cross-owner appointment detail IDs return 404 and do not disclose the other Owner's vehicle, service, notes, or appointment data.
- Query parameters purporting to supply a different Owner do not change scope.
- GET list/detail does not mutate status or appointment count; POST to read-only endpoints is rejected and has no side effect.
- Existing Plan 007 booking tests and all existing project tests remain passing.

## Migration and Environment Impact

No models, migrations, dependencies, environment variables, or setup changes are expected. The existing PostgreSQL configuration is used for validation. No transaction is needed for the read-only views.

## Open Questions

None blocking for list and detail. Cancellation eligibility remains unresolved and is deferred; no cancellation implementation begins until it is specified.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-27

## Implementation Report

- Summary: Implemented the Owner-scoped read-only appointment list and detail slice, including the PR #14 review corrections. Cancellation remains deferred because authoritative SRS FR-15 does not define eligible statuses.
- Files changed: `apps/appointments/views.py`, `apps/appointments/urls.py`, `apps/appointments/tests.py`, `templates/base.html`, `templates/appointments/appointment_list.html`, and `templates/appointments/appointment_detail.html`.
- Tests executed: `.venv/bin/python manage.py test apps.appointments.tests.OwnerAppointmentViewTests -v 2` — **9/9 passed**; `.venv/bin/python manage.py test apps.appointments apps.vehicles -v 2` — **80/80 passed**; `.venv/bin/python manage.py test -v 2` — **186/186 passed**; `.venv/bin/python manage.py check` — passed; `.venv/bin/python manage.py makemigrations --check` — no changes detected; `git diff --check` — passed. These results were run manually on PostgreSQL and recorded from the user's report; tests were not rerun during plan finalization.
- Test results: OwnerAppointmentViewTests: 9/9 passed. Appointments and Vehicles: 80/80 passed. Complete PostgreSQL suite: 186/186 passed. Django check passed. `makemigrations --check` reported no changes detected. `git diff --check` passed.
- Corrections and regression coverage: The appointment detail page renders an assigned Technician using the existing username representation, displays `Not assigned` when there is no Technician, and avoids exposing internal IDs or unrelated User data. The detail queryset loads Technician and User relationships with `select_related`. Added regression tests cover both Technician states and safe rendering. Added direct Owner empty-list coverage for HTTP 200, the empty-state message, and absence of another Owner's appointment row or link.
- Migration/environment changes: No Model or Migration changes. No environment or dependency changes.
- Security checks: Both views require login and OWNER role. List and detail querysets filter through `vehicle__owner=request.user`; cross-owner detail lookup returns 404. Tests passed for authorization, ownership, privacy, and read-only behavior. No mutation endpoint exists; GET is read-only and POST is rejected.
- Remaining risks: Cancellation eligibility remains unspecified by the authoritative SRS, so cancellation remains deferred.
- Deviations from plan: None. Cancellation was intentionally excluded because FR-15 does not define eligible statuses.
