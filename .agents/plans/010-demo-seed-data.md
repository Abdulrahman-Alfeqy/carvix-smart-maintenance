# Plan: Deterministic Demo Seed Data

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Arwa
- Reviewer: Abdalrahaman Atef
- Branch: feature/demo-seed-data
- Created: 2026-09-27
- Last updated: 2026-09-27

## Objective

Add an idempotent Django management command that creates or refreshes a deterministic, local demonstration dataset for existing CARVIX workflows, using existing models, constraints, and approved relationships. The command must not reset the database, delete arbitrary data, change schema, or store a committed demo password.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`.

- §1.6: the demonstration uses realistic seed data in a local production-like environment.
- §1.5.1 and §9.5: seed data supports the in-scope vehicle-maintenance workflow and demonstration preparation.
- FR-01–04 and Table 10: deterministic Owner, Technician, and Administrator users and TechnicianProfile role consistency.
- FR-05–08, FR-09, FR-11–14, FR-18–20 and Tables 6, 10–11: representative existing Vehicles, ServiceTypes, ServiceSlots, Appointments, MaintenanceRecords, SpareParts, and MaintenanceParts.
- §6.2–6.3 and NFR-D01–D04: respect existing relationships, status choices, nonnegative quantities/mileage, valid time ranges, capacity, and referential integrity.
- Plan 000's required normal-workflow-before-AI sequence; no AI or unfinished workflow is introduced.

## Current-State Analysis

- The current branch is `feature/demo-seed-data`, at the same commit as `main` (`15880001dd000aff5a78beb505d1495fd295a84c`). The worktree was clean at discovery; no Plan 011 changes were present.
- The installed Django apps include `apps.maintenance`, `apps.appointments`, `apps.vehicles`, `apps.authentication`, and `apps.inventory`. There is no existing management-command convention/package; `apps.core` is not installed and is unsuitable as the command host.
- `User` has unique username/email and OWNER, TECHNICIAN, ADMINISTRATOR roles. `TechnicianProfile.user` is one-to-one and `clean()` requires a TECHNICIAN user.
- `Vehicle` requires an Owner and nonnegative mileage; license plate is case-insensitively unique.
- `ServiceType` has unique name, positive kilometer/month/duration intervals, and nonnegative price.
- `ServiceSlot` requires timezone-aware start/end values with end after start and positive capacity. Appointment capacity is computed from active statuses (`PENDING`, `CONFIRMED`, `IN_PROGRESS`); an existing partial unique constraint protects active `(slot, vehicle)` duplicates.
- `MaintenanceRecord` requires Vehicle, ServiceType, TechnicianProfile, Appointment, date, and mileage. `clean()` rejects future service dates and requires its Vehicle, ServiceType, and TechnicianProfile to match the linked Appointment. Its due status is derived by `apps.maintenance.services.get_vehicle_maintenance_overview()` / `evaluate_due_services()`; it is not stored.
- `SparePart` has unique part number and nonnegative quantity, minimum stock, and unit price. `MaintenancePart` requires positive usage and a unique MaintenanceRecord/SparePart pair.
- There are no existing management commands. Existing tests use Django `TestCase`, and database-specific tests explicitly require PostgreSQL.
- Appointments have existing booking and Administrator assignment behavior, but no Technician completion workflow. Historical demonstration MaintenanceRecords require a linked Appointment and TechnicianProfile. The command may create internally consistent completed historical fixtures directly from existing model fields; this is seed data, not a status transition or workflow implementation. New Owner bookings use the already-implemented booking service.
- `README.md` contains no setup or demo-data instructions. `docs/README.md` identifies the DOCX as authoritative and supporting docs as non-authoritative.

## Proposed Changes

- `apps/maintenance/management/commands/seed_demo_data.py` (create): implement an atomic, deterministic command in an installed app. Use reserved stable demo identifiers, natural keys or seed-owned notes markers where supported, validate collisions rather than overwriting unrelated rows, and report seeded entity counts. Create at least two Owners, two Technicians, one Administrator, profiles only for Technicians, three multi-owner Vehicles, four ServiceTypes, active future slots with remaining capacity, an inactive historical slot, a capacity-bound slot, representative due-service history, and valid spare/usage records. Create future pending bookings through the existing booking service. Create completed historical Appointment/record pairs only to satisfy the current required MaintenanceRecord relationships; do not implement or simulate Technician workflow transitions.
- `apps/maintenance/test_seed_demo_data.py` (create): add isolated tests for successful command execution, repeated-run idempotency, entity counts and role/profile ownership, owner separation, model validation and due statuses, ServiceSlot states, appointment consistency, and SparePart/MaintenancePart constraints. Do not edit `apps/appointments/tests.py`.
- `docs/demo-seed-data.md` (create): document local command use, generated demo identities, optional demo-password environment variable strategy, and the fact that the command never resets or deletes data. No password or secret is committed.
- `.agents/plans/010-demo-seed-data.md` (create): track this approved task and finalize only after all required PostgreSQL validation succeeds.

No Appointment forms, services, views, URLs, or tests are changed. No models, migrations, settings, dependencies, SRS, unrelated UI, or Plan 011 files are changed.

## Risks and Problems

- A deterministic identity may already exist for an unrelated account. Use reserved usernames/emails and refuse mismatched collisions instead of changing that account.
- ServiceSlot has no natural-name or seed-marker field. Reuse slots through tagged seed-owned Appointments when available; create by an exact deterministic time/capacity tuple otherwise. Do not claim ownership of or update an arbitrary existing slot. Preserve external appointments and avoid changing slots used by non-seed Appointments.
- MaintenanceRecord cannot be seeded without its required Appointment and TechnicianProfile. Use only internally consistent historical fixtures with completed status, matching relations, and past dates. Do not add or depend on a completion workflow.
- A configured demo password would be sensitive if hard-coded. Default to unusable passwords and allow local sign-in only when a user-provided `CARVIX_DEMO_PASSWORD` environment variable is set. Never write or display that value.
- Idempotent updates must be limited to clearly identifiable seed-owned records. Do not flush, bulk-delete, or modify arbitrary users, vehicles, appointments, parts, or slots.
- Slots are time-sensitive. Use `timezone.now()` / `timezone.localdate()` and timezone-aware datetimes; future slots must remain future and historical slots inactive.
- PostgreSQL availability is required for all validation. If unavailable, stop at the first real failure and report the exact limitation; do not substitute SQLite.

## Alternatives Considered

### Option A — Installed-app command with reserved deterministic records (recommended)

Place one command in the installed maintenance app, use stable identifiers/seed-owned markers, and test through a dedicated module. Use existing domain services for new pending bookings and existing models for consistent historical fixtures.

Advantages: Django discovers the command; changes remain isolated from the concurrently developed Appointment workflow; no schema or dependency change; tests cover repeatability.

Disadvantages: the model has no explicit seed marker for ServiceSlot, so slot reuse needs conservative relation-based identification and collision handling.

### Option B — Add a custom seed registry/model or change models to tag fixtures

Advantages: seed ownership would be explicit for every row.

Disadvantages: requires schema changes and migrations, which are prohibited and unnecessary for this local task. Not selected.

## Recommended Approach

Choose Option A. A command under installed `apps.maintenance` is discoverable without changing configuration. Stable demo identities and existing marker-capable fields provide safe idempotency; ServiceSlots are handled conservatively because the current schema has no name/seed key. Existing models and the already-implemented booking service are sufficient.

## Implementation Steps

1. Create this approved Plan 010 and document discovered model constraints, the historical Appointment dependency, and credential strategy.
2. Add the isolated management command and dedicated test module; do not edit Appointment workflow code/tests.
3. Add local demo-data usage/credential documentation.
4. Run validation in the requested order on PostgreSQL and stop at the first failure.
5. Inspect the complete diff for genuine BLOCKER/HIGH/MEDIUM issues, confirm migration directories and model/schema boundaries, then complete the Implementation Report and mark IMPLEMENTED only if every gate passes.

## Test Plan

- Command succeeds and reports stable entity totals.
- Running twice leaves each seeded entity count and relationships unchanged and creates no duplicates.
- Required role counts exist; only TECHNICIAN users have seed TechnicianProfiles; no Owner/Administrator profiles are created.
- Vehicles belong to multiple expected Owners; ServiceTypes satisfy `full_clean()` and database constraints.
- Slots include active future available slots, an inactive slot, and a full slot; all use timezone-aware values and valid end/capacity constraints.
- Existing `get_vehicle_maintenance_overview()` reports `NO_HISTORY`, `NOT_DUE`, `DUE`, and `OVERDUE` for representative owner-owned Vehicle/service combinations.
- MaintenanceRecords have past/current dates, nonnegative mileage, and exact Appointment/Vehicle/ServiceType/Technician relation consistency.
- SpareParts and MaintenanceParts satisfy `full_clean()` and database constraints; usage rows do not mutate inventory quantities.
- Future pending Appointments use the existing booking service and satisfy current constraints; historical completed Appointment/record pairs satisfy existing relationships without implementing workflow transitions.
- No test edits `apps/appointments/tests.py`; `makemigrations --check` and migration-directory inspection verify no schema change.

## Migration and Environment Impact

No models or migrations, dependencies, database settings, environment configuration files, or production secrets change. PostgreSQL is required. The command optionally reads `CARVIX_DEMO_PASSWORD` from the process environment; when absent, created users have unusable passwords. Documentation must state this is local/demo-only and must not recommend a production password.

## Open Questions

None blocking. The required MaintenanceRecord-to-Appointment and TechnicianProfile dependencies are defined by current models. Historical completed appointments are static seed fixtures, not evidence of or implementation for Technician completion behavior.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-27

## Implementation Report

### Implementation Summary

Added an idempotent `seed_demo_data` management command in the installed maintenance app. It seeds deterministic Owner, Technician, and Administrator accounts; TechnicianProfiles only for Technician users; owner-separated Vehicles; existing ServiceTypes; future active and historical inactive ServiceSlots; pending bookings through the existing booking service; static completed historical Appointment/MaintenanceRecord pairs; SpareParts; and MaintenanceParts. The command is atomic, uses existing models and relationships, does not reset or delete database data, and refuses reserved-identity collisions rather than changing unrelated records.

### Files Created

- `.agents/plans/010-demo-seed-data.md`
- `apps/maintenance/management/__init__.py`
- `apps/maintenance/management/commands/__init__.py`
- `apps/maintenance/management/commands/seed_demo_data.py`
- `apps/maintenance/test_seed_demo_data.py`
- `docs/demo-seed-data.md`

No existing files were modified. No Plan 011, Appointment workflow, model, migration, settings, dependency, SRS, or unrelated files were changed.

### Seeded Entity Counts

- Users: **5** — 2 Owners, 2 Technicians, 1 Administrator.
- TechnicianProfiles: **2** — linked only to Technician users.
- Vehicles: **3** — 2 owned by the first Owner and 1 by the second Owner.
- ServiceTypes: **4**.
- ServiceSlots: **6** — 3 active future slots and 3 inactive historical slots; the future set includes a full slot and slots with remaining capacity.
- Appointments: **6** — 3 pending future bookings and 3 static completed historical records.
- MaintenanceRecords: **3**.
- SpareParts: **3**.
- MaintenanceParts: **2**.

The existing due-service evaluator reports `NO_HISTORY`, `NOT_DUE`, `DUE`, and `OVERDUE` for the seeded Owner Vehicle/service combinations. Future bookings use the existing booking service. Historical Appointment/MaintenanceRecord pairs satisfy the current required relationships and do not implement a Technician completion workflow. MaintenancePart usage does not mutate SparePart quantities.

### Idempotency and Credentials

The local PostgreSQL command was run twice successfully and produced matching entity counts without duplicates. The focused test also runs the command twice and verifies unchanged counts. Demo accounts have unusable passwords by default. Local sign-in can be enabled by setting `CARVIX_DEMO_PASSWORD` in the command process environment; the command does not print or store that value in source control.

### Validation Results

- Existing migrations applied successfully to the local database as setup; no migration files were generated or changed.
- `python manage.py seed_demo_data`: passed twice locally with matching counts.
- `python manage.py check`: passed; no issues identified.
- `python manage.py makemigrations --check`: passed; no changes detected.
- `python manage.py test apps.maintenance.test_seed_demo_data -v 2`: passed, **4 tests**.
- `python manage.py test -v 2`: passed, **199 tests**, `OK`.
- `git diff --check`: passed with no output or errors.
- Models and migrations: **no changes**.

These validation results were supplied after execution; tests and seed commands were not rerun during plan finalization.

### Deviations and Remaining Limitations

- No schema changes or Appointment production workflow changes were needed.
- ServiceSlot has no seed marker field. The command identifies seeded slots through tagged Appointments and refuses ambiguous unmarked slot collisions; it avoids shifting slots that have non-demo Appointments.
- Historical completed Appointments are static fixtures needed by the existing required MaintenanceRecord relationships; they do not represent or implement Technician assignment transitions or maintenance completion behavior.
- Deferred scope remains: Technician Appointment workflow, maintenance completion, inventory mutation, Owner appointment cancellation/rescheduling, general RBAC, dashboards, AgentActionLog, AI tools, Chat UI, and LLM integration.
