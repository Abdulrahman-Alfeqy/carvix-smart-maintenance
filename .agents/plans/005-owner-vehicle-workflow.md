# Plan: Owner Vehicle Management

## Metadata

- Status: APPROVED
- Related issue: N/A
- Owner: Arwa
- Reviewer: Abdalrahaman Atef
- Branch: feature/owner-vehicle-workflow
- Created: 2026-09-25
- Last updated: 2026-09-25

## Objective

Implement the Owner-facing Vehicle workflow: list, create, view, and update Vehicles owned by the authenticated Owner. This is roadmap item 5's normal workflow work, before the separate general ownership/RBAC work in item 6. Ownership and the narrow OWNER-role gate required by these endpoints are part of this workflow; a general RBAC framework is not.

## Requirements Covered

The sole authoritative requirements source is `docs/CARVIX_SRS_Group6.docx`, verified SHA-256 `c0f03e7c89b2b1d19594f35fffa5477aeb1a688aad605225af5c1a75abd9debf`. This plan covers FR-05, FR-06, and FR-07; NFR-S01, NFR-S02, NFR-S03, NFR-S04, NFR-U02, and NFR-D01; SRS section 4 Table 6 and section 4.1; SRS section 6 Table 11 and section 6.3; user journey UJ-02; and roadmap item 5.

The Vehicle scope is list, registration, detail, and update. FR-05 requires registration with `request.user` as owner; FR-06 specifies viewing and updating only one's own Vehicles; FR-07 requires unique license plates and non-negative mileage. Table 6 grants Owners Full access to their own Vehicles, with Full defined as create/read/update/delete “where applicable.” Here, deletion is not applicable to this workflow: the detailed vehicle requirements and UJ-02 define no delete endpoint, journey, acceptance criterion, confirmation flow, or historical-data behavior. Therefore Vehicle deletion is excluded. Any future deletion workflow requires its own approved plan and must specify confirmation, authorization, CSRF, POST-only mutation, protected related-record behavior, and user feedback.

Acceptance: a valid Vehicle is saved with `request.user` as owner; only OWNER users can use these Owner-facing endpoints; Owners can list and access only their own Vehicles; invalid data receives field-specific errors; and changing a URL identifier cannot expose or modify another Owner's Vehicle.

## Current-State Analysis

`apps/vehicles/models.py` already defines the approved Vehicle fields, normalization, case-insensitive license-plate uniqueness through the PostgreSQL functional constraint `vehicles_plate_ci_uniq`, non-negative mileage validation, and database constraints. `Vehicle.save()` performs approved normalization without calling `full_clean()`. Existing model tests cover normalization and PostgreSQL constraints. Authentication uses namespaced URLs and class-based views; `LOGIN_URL` is `authentication:login`. The base template displays the domain role and uses a CSRF-protected POST logout form.

## Proposed Changes

- Create `apps/vehicles/forms.py` with an explicit ModelForm allowlist containing exactly `manufacturer`, `model`, `model_year`, `license_plate`, and `current_mileage`. Exclude `owner` and `created_at`. Normalize the submitted plate consistently with the existing Vehicle normalization. Check for case-insensitive duplicates against other Vehicles, excluding the current instance on update, and attach the normal duplicate error to `license_plate`. Do not modify the model or add `unique=True`. Retain `vehicles_plate_ci_uniq` as the final database invariant. Do not swallow unrelated `IntegrityError` exceptions; graceful handling of the known save-time plate conflict may be added if needed, but a complex race test is not required.
- Create `apps/vehicles/views.py` with list, create, detail, and update class-based views. Use `LoginRequiredMixin` before a narrowly scoped OWNER-role guard before each generic view base, so anonymous requests take the login redirect path and authenticated non-Owners receive 403. Check the CARVIX `role`; do not use `is_staff` or `is_superuser`. Establish ownership only from `request.user`; filter the list by `owner=request.user`; and filter detail/update querysets by owner before object retrieval. Assign `request.user` during create and preserve the existing owner during update.
- Create `apps/vehicles/urls.py` with `app_name = "vehicles"` and stable names `vehicle-list`, `vehicle-create`, `vehicle-detail`, and `vehicle-update`; include these URLs from `config/urls.py` without changing authentication URL semantics. Do not add a delete URL or any state-changing GET endpoint.
- Add minimal list, detail, and shared create/update templates using the existing base template. Add an Owner-only Vehicles navigation link. Link visibility is presentation only; backend authorization applies to direct requests independently.
- Extend `apps/vehicles/tests.py` with the focused functional, authorization, ownership, mass-assignment, validation, CSRF, GET-safety, navigation, and regression coverage below.
- Do not modify the Vehicle model, migrations, authentication files, settings, dependencies, or other applications.

### Explicit Exclusions

Exclude Vehicle deletion; FR-08 maintenance history; FR-11 due-service calculation; Administrator Vehicle management through a separate administrative workflow; Technician assigned-Vehicle workflows; general project-wide RBAC and generic permission engines; appointments; maintenance workflows; inventory; dashboards; AgentActionLog; Chat UI; AI tools; and LLM integration. Do not describe this task as CRUD in a way that implies deletion. Administrator denial from these Owner-facing endpoints does not remove the SRS permission for a separately approved Administrator Vehicle-management workflow.

## Risks and Problems

The principal risks are cross-owner IDOR, ownership mass assignment, role bypass, unauthorized mutation, CSRF, and database uniqueness errors without field feedback. Scope queries by `owner=request.user` before retrieving objects; never bind owner from client data; enforce the OWNER domain role on all four endpoints; return 404 for another Owner's Vehicle identifier and 403 for authenticated Technician or Administrator access to these Owner endpoints. An unauthorized update POST must not change the target Vehicle. Do not use `is_staff` or `is_superuser` as CARVIX domain roles.

List and detail are read-only GET endpoints. Create GET displays an unbound form and creates no Vehicle; update GET displays the form and changes no Vehicle fields. All state changes occur through POST, with CSRF protection. Successful create and update redirect using named URLs. UI visibility is not authorization.

The normal duplicate-plate path must normalize consistently, check the case-insensitive uniqueness rule in the form, and report a `license_plate` field error. On update, validation excludes the current Vehicle. The database functional constraint remains authoritative if a conflict occurs at save time. Do not change the model to solve a form-layer issue, create a general database-conflict framework, or swallow unrelated database errors. Reject negative mileage on the `current_mileage` field. Preserve Arabic characters, digits, and meaningful internal separators. Do not invent a model-year range.

Deletion remains outside this workflow. If a future approved task introduces permanent Vehicle deletion or another critical destructive operation, it must require explicit user confirmation or two-step validation, POST-only mutation, CSRF, authentication, role and ownership authorization, defined behavior for protected appointments and maintenance history, and safe feedback when deletion is prohibited.

## Alternatives Considered

### Option A

Use class-based views with a small Vehicles-local OWNER role guard. This follows the existing authentication view style and avoids a project-wide authorization abstraction.

### Option B

Use function-based views with explicit per-view checks. This is viable but differs from the repository's current class-based authentication workflow. A broad RBAC framework is also possible later, but exceeds this workflow's scope and is not introduced here.

## Recommended Approach

Use class-based views with the smallest app-local OWNER authorization guard required for this workflow. Order each endpoint's bases as `LoginRequiredMixin`, the OWNER-role guard (or equivalent `UserPassesTestMixin`), then its generic view base. This ensures anonymous redirect behavior precedes the role check and authenticated wrong-role requests receive 403. The guard checks the CARVIX role value. Owner-scoped querysets make cross-owner detail/update retrieval return 404 before object access. The create view assigns `request.user`; the update form cannot change ownership. ModelForm validation supplies field-specific feedback, existing normalization remains in place, and PostgreSQL constraints continue protecting supported invariants. Do not add a model-year minimum, maximum, or future-year rule. Do not implement Vehicle deletion.

## Implementation Steps

1. Add the explicit Vehicle ModelForm, normalization and case-insensitive duplicate validation, and the local authenticated OWNER-role enforcement.
2. Add list/create/detail/update views with the specified mixin order, owner-scoped retrieval, server-side ownership assignment, POST-only mutation, and named success redirects.
3. Add namespaced URLs, include them in project routing, add minimal templates, and show the Owner-only navigation link.
4. Add the focused tests below. Run the relevant PostgreSQL tests first, verify no model migration is needed with a dry-run migration check and migration-directory inspection, then run the complete PostgreSQL regression suite.

## Test Plan

- Anonymous list, create, detail, and update requests redirect to the configured login page.
- OWNER can load the list; it contains own Vehicles and excludes other Owners' Vehicles. OWNER can create a Vehicle with themselves as owner, view own detail, and update own Vehicle without changing ownership. Successful create/update redirect correctly by named URL.
- TECHNICIAN receives 403 on list, create, detail, and update. ADMINISTRATOR also receives 403 on all four Owner-facing endpoints; this does not test or define separate Administrator management. Do not use staff/superuser flags for domain-role decisions.
- Another Owner's detail URL, update GET, and update POST return 404. The unauthorized POST has no side effect and the target Vehicle remains unchanged.
- Create GET displays an unbound form and creates no Vehicle. Update GET displays the form and leaves every Vehicle field unchanged. List/detail GETs are read-only; no state-changing GET endpoint exists.
- `owner` and `created_at` are absent from the exact five-field form; submitted `owner` or `owner_id` values cannot set or change ownership.
- Duplicate case-insensitive plates on create and update produce a `license_plate` field error; update validation excludes the current Vehicle. Negative mileage produces a `current_mileage` field error. Required-field errors are field-specific. Arabic characters, digits, and meaningful internal separators are preserved by plate normalization. No model-year range is enforced.
- An enforcing CSRF test client rejects create and update POST requests without a token with 403.
- OWNER sees the Owner Vehicles navigation link; TECHNICIAN and ADMINISTRATOR do not. Tests also verify direct backend requests remain protected regardless of navigation visibility.
- Existing Vehicle model tests and authentication tests remain unchanged unless a direct documented need exists. Run the full PostgreSQL test suite.
- `python manage.py makemigrations --check --dry-run` reports no model changes, and migration-directory inspection confirms no migration file was created.

## Migration and Environment Impact

MIGRATIONS_EXPECTED: NO. No model, environment, dependency, or setup changes are expected. Verify with `python manage.py makemigrations --check --dry-run` and inspect `apps/vehicles/migrations/`; do not generate a migration. Roll back by reverting this workflow's routes, views, form, templates, navigation, and tests. No schema change or Vehicle deletion is involved.

## Definition of Done

- The approved Owner list/create/detail/update acceptance criteria are met with the role, ownership, validation, CSRF, GET-safety, and navigation behavior in this plan.
- Required focused tests and the full PostgreSQL regression suite pass.
- No model change or migration is introduced; no deletion operation or broad RBAC framework is added.
- The implementation matches this plan, and the pull request reports test results and migration impact.

## Open Questions

None blocking.

Resolved decisions:

- Vehicle deletion is excluded; any future deletion task is separate and must define destructive-action confirmation and safe protected-history behavior.
- Destructive-action confirmation applies if deletion is introduced in a future approved task; it does not require deletion in Plan 005.
- Technician and Administrator users receive 403 on Owner-facing Vehicle endpoints.
- Cross-owner identifiers return 404; unauthorized update POST has no side effect.
- GET requests do not mutate state; ownership derives only from `request.user`.
- Normal duplicate plates produce a `license_plate` field error; PostgreSQL remains the final uniqueness invariant.
- No Vehicle model change or migration is expected.
- General RBAC remains deferred.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-25

Implementation must not begin while Status is `DRAFT` or Decision is `PENDING`.

## Implementation Report

- Summary:
- Files changed:
- Tests executed:
- Test results:
- Migration/environment changes:
- Security checks:
- Remaining risks:
- Deviations from plan:
