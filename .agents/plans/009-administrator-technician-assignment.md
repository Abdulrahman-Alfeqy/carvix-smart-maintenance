# Plan: Administrator Technician Assignment

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/administrator-technician-assignment
- Created: 2026-09-27
- Last updated: 2026-09-27

## Objective

Provide a narrow Administrator workflow to assign an available TechnicianProfile to an Appointment that has no Technician assigned. Preserve Appointment status and all other data. Do not implement reassignment or infer status eligibility.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`.

- FR-18: “The system shall allow administrators to assign technicians to appointments.” Acceptance: “The selected technician and appointment are updated.”
- Table 10 and Table 11 define the `TechnicianProfile`–`Appointment` assignment relationship and Appointment's nullable `technician_id`; Table 11 identifies TechnicianProfile's User relationship and Technician role expectation.
- FR-04 and the SRS role/access requirements require role-aware authorization and denial for unauthorized roles.
- Plan 004 accepted the `TechnicianProfile.is_available` model field as supporting assignment of available Technicians and records that Technician role validation belongs at the application boundary as well as model validation.

FR-18 does not define eligible Appointment statuses, reassignment behavior, or any status transition after assignment. This plan implements initial assignment only for currently unassigned Appointments, imposes no new status filter, leaves the existing status unchanged, and defers reassignment. These ambiguities are not silently resolved as general business rules.

## Current-State Analysis

- `apps/appointments/models.py` defines `Appointment.technician` as a nullable ForeignKey to `TechnicianProfile`; current statuses are `PENDING`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`. No assignment transition or eligibility policy exists in the model.
- `apps/maintenance/models.py` defines `TechnicianProfile(user, specialization, is_available)`. Its `clean()` requires the related User role to be TECHNICIAN, but direct ORM saves do not invoke `full_clean()`, so assignment must independently validate role and availability.
- `apps/appointments/admin.py` exposes Appointment through the default Django ModelAdmin. Its change form can edit broad Appointment fields and its access gate is Django `is_staff`/permissions; it does not provide the required exact CARVIX ADMINISTRATOR role check or limit selection to available Technician-role profiles. It does not safely satisfy this workflow as currently configured.
- `apps/authentication.models.User.Role` is the authority for OWNER, TECHNICIAN, and ADMINISTRATOR. Existing Owner endpoints use `LoginRequiredMixin` before a domain-role `UserPassesTestMixin`; appointment URLs are already included in project routes.
- PostgreSQL readiness preflight returned `/var/run/postgresql:5432 - no response`. Existing service startup was attempted non-interactively; current execution lacks root/postgres service-owner access. Per the task instructions, tests must not run while PostgreSQL remains unavailable.

## Proposed Changes

- `apps/appointments/forms.py`: add an allowlisted assignment form containing only an available `TechnicianProfile` whose related User role is TECHNICIAN and a required explicit confirmation checkbox. Do not accept actor, status, or other Appointment fields.
- `apps/appointments/services.py`: add a domain assignment service taking the server-side actor and validated Appointment/Technician identifiers. Recheck exact ADMINISTRATOR role, Appointment existence and unassigned state, and TechnicianProfile existence, availability, and related User role. Use `transaction.atomic()` and lock the Appointment row to prevent concurrent initial assignments from overwriting one another. Update only `technician`; preserve status and all unrelated fields. Return success only after the transaction persists.
- `apps/appointments/views.py`: add a local Administrator-role mixin, an unassigned Appointment list, and a confirmed assignment FormView. Anonymous requests redirect to the login URL; authenticated OWNER and TECHNICIAN users receive 403. Filter protected selections on GET and revalidate them through the service on POST. GET is read-only.
- `apps/appointments/urls.py`: add namespaced assignment list/form routes without changing the Owner appointment or booking routes.
- `templates/appointments/administrator_assignment_list.html` and `administrator_assignment_form.html`: present unassigned appointments and the selected appointment details; provide the Technician choice, required confirmation, CSRF token, and explicit confirm button.
- `templates/base.html`: show the assignment navigation entry only to a user whose domain role is ADMINISTRATOR. This is presentation only; endpoint authorization remains enforced.
- `apps/appointments/tests.py`: add focused authorization, input validation, initial assignment, no-reassignment, unchanged-status/data, GET safety, CSRF, and missing-object tests; retain all existing Owner booking/list/detail tests unchanged.

## Scope

- ADMINISTRATOR may assign an available TechnicianProfile linked to a User with role TECHNICIAN to an Appointment whose `technician` is currently null.
- Appointments are not filtered by status because FR-18 supplies no status eligibility rule. Assignment does not change the stored status.
- Existing assignments cannot be replaced by this workflow. Reassignment is deferred.
- Actor identity comes exclusively from `request.user`.
- A required confirmation field and POST are required to mutate; Django CSRF middleware protects POST.
- No Model, Migration, settings, dependency, SRS, architecture, or ERD changes.

## Out of Scope

Appointment reassignment; Appointment status transitions or status-based assignment eligibility; Owner cancellation; Technician status workflow; maintenance completion; MaintenanceRecord creation; inventory; dashboards; generic RBAC; AgentActionLog; AI tools; Chat UI; LLM; model or migration changes; new dependencies; unrelated UI redesign; changes to the authoritative SRS or architecture.

## Authorization and Validation Rules

- Require authentication first. Anonymous requests redirect to `authentication:login`.
- Check `request.user.role == User.Role.ADMINISTRATOR` on every assignment endpoint; do not authorize using `is_staff` or `is_superuser`.
- Authenticated OWNER and TECHNICIAN actors receive 403 on both assignment endpoints, regardless of staff flags.
- Do not accept Administrator identity from form, query, or URL parameters.
- Only unassigned Appointment records appear and resolve for initial assignment. A missing Appointment returns 404; an already-assigned Appointment is not eligible for this initial-assignment route and is not overwritten.
- Only available TechnicianProfiles whose related account role is TECHNICIAN are choices. Revalidate in the service so forged or stale identifiers cannot bypass form choices. Owner/Administrator accounts, unavailable profiles, malformed IDs, and nonexistent profiles are rejected without mutation.
- Form fields are allowlisted; only the Technician selection and explicit confirmation are accepted. Appointment status, notes, vehicle, service, slot, and other relations are preserved.
- GET does not mutate. POST requires confirmation and CSRF.

## Transaction Decision

Assignment is one-row mutation, but `transaction.atomic()` with `select_for_update()` on the Appointment row is justified to preserve the initial-assignment-only rule under concurrent Administrator submissions. Inside the transaction, re-fetch the Appointment, reject an existing assignment, re-fetch and validate the TechnicianProfile and its related User role/availability, then update only `technician`. No other row is written and no schema change is needed.

## Risks and Problems

- A forged Technician identifier could bind an Owner or Administrator account if the view trusts a browser-supplied foreign key. Restrict choices in the form and repeat role/availability validation in the service.
- A staff-based permission check could admit a non-Administrator or exclude a domain Administrator. Enforce the CARVIX role directly on the endpoint.
- Concurrent submissions could replace the first assignment unless the Appointment row is serialized; use the justified row lock and reject after re-reading a non-null assignment.
- The SRS is silent on assignment eligibility by status and on reassignment. Keep all current statuses unchanged, apply no invented status filter, and support only initial assignment. Reassignment and status eligibility need future SRS-backed decisions.
- PostgreSQL is currently unavailable to this execution context. The existing service start commands require root/service-owner access; tests and final IMPLEMENTED status are gated on successful PostgreSQL validation.

## Alternatives Considered

### Option A — Narrow domain-role assignment pages (recommended)

Add a small appointments-local Administrator list/form/service using `request.user.role`, existing TechnicianProfile data, explicit confirmation, and a transaction for initial assignment only.

Advantages: satisfies FR-18 with exact domain authorization, validates Technician role and availability, limits changes to the Technician relation, and does not expand the model or implement a status workflow.

Disadvantages: adds two small templates and a scoped workflow where default Django Admin UI already exists.

### Option B — Use the current Django ModelAdmin as-is

Advantages: no custom list/form views or templates.

Disadvantages: current ModelAdmin relies on Django staff permissions, allows broad Appointment field edits including status, and does not restrict Technician selection to available Technician-role profiles. It does not satisfy the stated domain authorization and field-preservation requirements without substantial customization. Not selected.

## Recommended Approach

Choose Option A. The SRS requires Administrator assignment and explicitly calls for the selected Technician and Appointment to be updated. Existing Django Admin does not enforce the approved CARVIX role or narrowly validate the assignment. A focused assignment workflow is the smallest secure implementation. Limit it to currently unassigned Appointments, accept available TechnicianProfiles linked to TECHNICIAN accounts, and leave status and all other fields unchanged. Defer reassignment and status eligibility.

## Implementation Steps

Implement the assignment form/service/views/routes/templates/navigation in one coherent pass, add focused regression tests without modifying or weakening existing tests, then execute validation in the prescribed order if PostgreSQL is ready.

## Test Plan

- Anonymous requests to list and assignment form redirect to login.
- ADMINISTRATOR can access the list and successfully assign an available TECHNICIAN profile to an unassigned Appointment.
- OWNER and TECHNICIAN receive 403 on both endpoints, including when test users have staff flags.
- GET list/form does not change Appointment or Technician data.
- POST without CSRF is rejected; valid CSRF GET/POST round trip assigns only after explicit confirmation.
- Owner-role and Administrator-role accounts with crafted TechnicianProfile rows are rejected; unavailable TechnicianProfile is rejected; valid TECHNICIAN profile is accepted.
- Forged/malformed/nonexistent TechnicianProfile identifiers cause no change; nonexistent Appointment returns 404.
- A previously assigned Appointment is not overwritten; reassignment remains unavailable.
- Assignment preserves Appointment status, notes, vehicle, service, slot, `booked_by_agent`, and existing unrelated fields.
- Existing Plan 007 booking and Plan 008 Owner list/detail tests remain passing.

## Migration and Environment Impact

No Model or Migration changes, dependencies, environment variables, or setup changes are expected. Use the existing PostgreSQL test environment only. No database recreation or SQLite substitute is allowed. If PostgreSQL remains unavailable because service startup requires human sudo/service-owner access, report the exact startup/readiness errors, do not run tests, and leave the plan APPROVED rather than claiming completion.

## Definition of Done

- FR-18 initial Technician assignment works through authenticated Administrator-only endpoints.
- Technician role and availability are validated server-side; forged identifiers do not mutate Appointment data.
- Initial assignment requires confirmed CSRF-protected POST, is concurrency-safe, and preserves status and unrelated fields.
- Reassignment, status eligibility, and status transitions remain deferred.
- Focused, Appointments/Vehicles, and full PostgreSQL suites pass; Django check, migration check, whitespace check, and migration-boundary inspection pass.
- No Model, Migration, dependency, SRS, or unrelated changes are introduced.

## Open Questions

None blocking for the approved initial-assignment-only scope. Reassignment and status eligibility remain explicitly deferred because the SRS does not specify them.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-27

## Implementation Report

- Summary: Implemented and validated the initial Administrator assignment workflow for available TechnicianProfiles on unassigned Appointments. Existing Appointment status and all unrelated fields are preserved. Reassignment and status-based eligibility remain deferred.
- Files created: `.agents/plans/009-administrator-technician-assignment.md`; `templates/appointments/administrator_assignment_list.html`; `templates/appointments/administrator_assignment_form.html`.
- Files modified: `apps/appointments/forms.py`, `apps/appointments/services.py`, `apps/appointments/views.py`, `apps/appointments/urls.py`, `apps/appointments/tests.py`, and `templates/base.html`.
- Tests executed on PostgreSQL (verified terminal results supplied for finalization): `.venv/bin/python manage.py test apps.appointments.tests.AdministratorAssignmentViewTests -v 2` — **9/9 passed**; `.venv/bin/python manage.py test apps.appointments apps.vehicles -v 2` — **89/89 passed**; `.venv/bin/python manage.py test -v 2` — **195/195 passed**.
- Test results: AdministratorAssignmentViewTests: 9/9 passed. Appointments and Vehicles: 89/89 passed. Complete PostgreSQL suite: 195/195 passed. Django system check passed. `makemigrations --check` reported “No changes detected.” `git diff --check` passed.
- Migration/environment changes: No Model or Migration changes. No database settings, `.env`, environment variables, or dependencies were changed.
- Security checks: Assignment endpoints require exact `request.user.role == ADMINISTRATOR`; anonymous requests redirect to login, and OWNER/TECHNICIAN roles receive 403, independent of staff flags. Only available TechnicianProfiles linked to TECHNICIAN accounts are offered and the service re-fetches and revalidates the selected profile. Actor identity and Appointment status are not accepted from client input. The confirmed form submits by POST with CSRF protection; GET is read-only. The service uses `transaction.atomic()` and locks/re-fetches the Appointment, rejects an existing assignment, and updates only `technician`. No IntegrityError is caught or hidden. Tests passed for authorization, invalid identifiers/profiles, CSRF, preservation of unrelated fields, and initial assignment behavior.
- Diff review: No BLOCKER, HIGH, or MEDIUM findings. Existing Plan 007 booking and Plan 008 Owner list/detail behavior remain covered by the passing regression suites. No cancellation, reassignment, or status-transition implementation was added.
- Remaining risks and deferred scope: The authoritative SRS does not define status-based assignment eligibility or reassignment behavior. This workflow assigns only unassigned Appointments without filtering by status and does not support reassignment or change status.
- Deviations from plan: None.
