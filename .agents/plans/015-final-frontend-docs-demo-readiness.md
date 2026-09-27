# Plan: Final Frontend, Role Entry Points, README, and Demo Documentation

## Metadata

- Status: APPROVED
- Related issue: N/A
- Owner: Project team
- Reviewer: Project team
- Branch: feature/frontend-docs-demo-readiness
- Created: 2026-09-27
- Last updated: 2026-09-28

## Objective

Improve presentation of the existing CARVIX Django-rendered pages, make existing role workflows easier to find, document reproducible local setup, and prepare a truthful 15-minute demo runbook. Preserve every route, form field, POST/CSRF behavior, permission check, message, and business workflow.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`.

- FR-01–04: registration, authentication, profile, and role entry points.
- FR-05–08 and FR-11: Owner vehicle pages, ownership-protected history, and due-service presentation.
- FR-12–15: Owner slot booking, appointments, and existing appointment management presentation.
- FR-16–18: assigned Technician pages and Administrator assignment presentation.
- FR-35: documentation for authorized AgentActionLog inspection.
- NFR-P01: normal pages support local demo responsiveness; do not add expensive presentation queries.
- NFR-U01: responsive pages usable at common desktop/mobile widths.
- NFR-U02: clear existing field-specific form errors.
- NFR-S01–04: preserve authentication, CSRF, ownership, and role protections; frontend visibility is not authorization.
- SRS §9.5 and §9.6, Appendix A/B: README, seed data, rehearsed demo, responsive templates, traceability, screenshots, and reproducibility.
- User journeys UJ-01–07 as relevant to already implemented non-AI workflows.

## Current-State Analysis

- Shared templates live in `templates/`; authentication, Owner, Technician, and Administrator pages are grouped by feature.
- `templates/base.html` provides minimal navigation and Django message rendering. Profile is the shared post-login landing page; there are no role dashboards.
- Project-level `static/` initially contained only `.gitkeep`; no stylesheet or framework is installed. `STATICFILES_FINDERS` includes `AppDirectoriesFinder` but `STATICFILES_DIRS` is not configured, so the repository-root `static/css/` path alone is not discovered by Django. To honor the no-settings-change boundary, the same general stylesheet must also be present under the installed `apps.authentication/static/css/` path for local and collected static serving.
- Existing pages already include CSRF tokens on state-changing forms, display form errors, and provide several workflow empty states. Keep their behavior and wording relied on by tests.
- `README.md` is a short project summary, not a setup guide. `docs/demo-seed-data.md` already documents safe deterministic local seed use and password handling. `docs/README.md` identifies the DOCX SRS as authoritative.
- Supporting architecture/ERD/user-journey documents include older or speculative details; new documentation will label them supporting and will not present unsupported features as implemented.
- Current branch is `feature/frontend-docs-demo-readiness`, clean at discovery; current HEAD equals `main` (`b028e499ee0c2d30d31fd0a07af1c42dcd0ccbb7`).
- Plan 014 is developed separately. Shared base/profile templates may conflict; coordinate its final integration and avoid all `apps/ai_agent/` files and AI/chat UI.
- Seed command is `python manage.py seed_demo_data`; it creates 5 users, 2 TechnicianProfiles, 3 Vehicles, 4 ServiceTypes, 6 ServiceSlots, 6 Appointments, 3 MaintenanceRecords, 3 SpareParts, and 2 MaintenanceParts. Demo passwords are unusable by default; optional `CARVIX_DEMO_PASSWORD` is local-only and is never printed.
- AgentActionLog uses the standard Admin route `/admin/ai_agent/agentactionlog/`; inspection requires authorized Django Admin access and the Administrator role. Logs may be empty until an approved workflow creates entries.

## Scope and Boundaries

Presentation-only improvements to the existing shared, authentication, Owner, Technician, and Administrator templates; a general-purpose responsive stylesheet; README setup/architecture/demo guidance; and a demo runbook. No backend behavior, data model, migration, URL configuration, settings, dependency, business logic, workflow, AI, or chat change.

## Proposed Files

### Create

- `.agents/plans/015-final-frontend-docs-demo-readiness.md`
- `static/css/carvix.css`
- `apps/authentication/static/css/carvix.css` (identical staticfiles-discoverable copy; necessary because `config/settings.py` is out of scope and the root static directory is not registered)
- `docs/demo-runbook.md`

### Modify

- `templates/base.html`
- `templates/authentication/login.html`
- `templates/authentication/register.html`
- `templates/authentication/profile.html`
- `templates/authentication/profile_edit.html`
- `templates/vehicles/vehicle_list.html`
- `templates/vehicles/vehicle_form.html`
- `templates/vehicles/vehicle_detail.html`
- `templates/appointments/booking_form.html`
- `templates/appointments/appointment_list.html`
- `templates/appointments/appointment_detail.html`
- `templates/appointments/technician_appointment_list.html`
- `templates/appointments/technician_appointment_detail.html`
- `templates/appointments/technician_maintenance_completion.html`
- `templates/appointments/administrator_assignment_list.html`
- `templates/appointments/administrator_assignment_form.html`
- `README.md`

No tests or application Python files are planned for modification. Keep existing text and named links stable where tests or behavior rely on them. Do not modify `docs/CARVIX_SRS_Group6.docx`, `docs/demo-seed-data.md`, `config/settings.py`, `config/urls.py`, or anything in `apps/ai_agent/`.

## UI Rules

- Load the stylesheet from `templates/base.html` using Django's static template tag; do not add configuration or dependencies.
- Keep responsive CSS generic and reusable; no chat/AI-specific styling, placeholder, or entry point.
- Preserve existing navigation destinations and role conditions. Any Admin link is a convenience only; Django Admin permissions and role gate remain authoritative.
- Profile may receive small role-aware links to existing endpoints only. Do not add or imply new backend capabilities.
- Retain labels, names, IDs, values, CSRF tags, method/action attributes, form errors, success/error message content, and workflow controls.
- Use semantic landmarks, accessible headings/focus states, and consistent presentation for messages, errors, lists, cards, and empty states without doing business calculations in templates.

## README and Demo Documentation

README will cover supported Python/Django/PostgreSQL versions, virtual environment and dependency installation, PostgreSQL/database setup, `.env.example` copying and required variable names, migrations, optional safe local demo password setup, seed command, server run, test commands, architecture overview, and relevant repository documentation/file paths. Do not disclose `.env` values or passwords.

`docs/demo-runbook.md` will provide a timed 15-minute script and role/workflow order, SRS traceability checklist, screenshots checklist, safe local preparation, and AgentActionLog Admin path/access instructions. It will explicitly state that logs may be empty until an approved workflow generates records, and will distinguish current implemented flows from deferred AI behavior.

## Risks and Conflicts

- Plan 014 may touch the shared base/profile integration points. Reconcile its final changes before editing those templates; never modify its files.
- Presentation edits can accidentally remove form controls, CSRF tags, named routes, conditional controls, or text assertions. Preserve markup semantics and run workflow regression tests.
- README and demo instructions can become misleading if they claim future workflows are already implemented; map every demo step to current code and the SRS.
- Responsive CSS can hide or truncate controls at narrow widths; verify representative desktop and mobile widths.
- Django messages must remain escaped and accessible; do not introduce unsafe HTML or JavaScript.
- The AgentActionLog page may display no rows because current seed/workflow does not create records; document that accurately.

## Alternatives Considered

### Option A — Small shared CSS and template-only presentation pass (Recommended)

Use one responsive stylesheet, improve existing templates and existing profile entry points, and document current workflows. This stays within the requested frontend-only scope and avoids schema, route, or business changes.

### Option B — Add new dashboard views, APIs, or a frontend framework

This could create richer role dashboards but adds backend behavior, dependencies, routes, and merge risk with Plan 014. It is outside this plan's boundaries.

## Recommended Approach

Use Option A. Keep changes reviewable and preserve current Django MVT workflows. Coordinate shared templates with Plan 014; defer any overlapping chat/dashboard integration to that plan's owner.

## Implementation Steps

1. Confirm the approved paths and Plan 014 integration state; record this approved plan.
2. Add matching `static/css/carvix.css` and `apps/authentication/static/css/carvix.css`, integrate the discoverable asset safely in the shared base, and apply only minimal layout/navigation presentation changes.
3. Keep the two CSS files identical; improve the listed authentication, Owner, Technician, and Administrator templates without changing routes, forms, authorization, or messages.
4. Expand README setup and architecture documentation using repository-verified commands and safe credential instructions.
5. Create `docs/demo-runbook.md` with the timed script, traceability and screenshot checklists, safe demo preparation, and Admin log instructions/limitation.
6. Run checks, targeted workflow and seed tests, full suite, and whitespace validation; manually inspect responsive views and review the complete diff for boundaries and accuracy.

## Test Plan and Acceptance Criteria

- Django system check succeeds and `makemigrations --check` reports no model changes.
- Authentication, vehicle, and appointment test suites pass unchanged, including route, role, CSRF, form, and message behavior.
- Demo seed tests pass without invoking the seed command against a shared database.
- Full project suite passes on configured PostgreSQL.
- `git diff --check` passes.
- Manually inspect login/registration, profile, Owner vehicle and appointment pages, Technician queue/detail/completion, and Administrator assignment at desktop and mobile widths.
- Verify all existing URLs and form fields/actions/methods/CSRF tokens remain present and functional.
- Verify README and runbook use only real local setup names/commands, reveal no credentials, link to the authoritative SRS, accurately label supporting documentation, and distinguish implemented/deferred behavior.
- Verify Plan 014 and all `apps/ai_agent/` paths remain untouched; verify no backend, model, migration, settings, URL, or business-logic files changed.

## Validation Commands

1. `.venv\Scripts\python.exe manage.py check`
2. `.venv\Scripts\python.exe manage.py makemigrations --check`
3. `.venv\Scripts\python.exe manage.py test apps.authentication.tests apps.vehicles.tests apps.appointments.tests -v 2`
4. `.venv\Scripts\python.exe manage.py test apps.maintenance.test_seed_demo_data -v 2`
5. `.venv\Scripts\python.exe manage.py test -v 2`
6. `git diff --check`

No shared-database seed command is run. If PostgreSQL is unavailable or a validation gate fails, stop and report the exact outcome; do not substitute SQLite or claim success.

## Migration and Environment Impact

No model, migration, setting, URL, dependency, or environment configuration change is permitted. Because the root static directory is not discoverable and settings.py is forbidden, maintain the same approved general stylesheet at both `static/css/carvix.css` and `apps/authentication/static/css/carvix.css`. README may document `.env.example` variable names and safe setup but must not contain actual secret values.

## Open Questions

None blocking. Plan 014’s shared-template overlap must be reconciled by inspecting its final changes before the base/profile edits; if the branch is not available for inspection, preserve those files minimally and report the integration risk.

## Approval

- Decision: APPROVED
- Approved by: User
- Approval date: 2026-09-27

## Implementation Report

Pending implementation and validation.
