# Plan: CARVIX Core Domain Models

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Arwa
- Reviewer: Abdalrahaman Atef
- Branch: feature/core-domain-models
- Created: 2026-09-25
- Last updated: 2026-09-25

## Objective

Define the smallest SRS-approved database-model foundation for the traditional CARVIX workflows: vehicle ownership and management, technician-specific data, service definitions with maintenance intervals, service-slot scheduling with capacity, appointment booking with technician assignment, maintenance history, spare-parts inventory, and parts used during maintenance.

This task plans approved models, migrations, model tests, and minimal Django Admin registration. The plan is approved for implementation. Implementation must remain within the approved scope and must follow the migration, human-review, PostgreSQL, and testing gates defined in this plan.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`, Document Version 1.0, status Initial Approved Baseline, SHA-256 `c0f03e7c89b2b1d19594f35fffa5477aeb1a688aad605225af5c1a75abd9debf`, read via the complete 842-line extraction (199 paragraphs, 19 tables, 181 table rows).

- FR-05 — owners register vehicles; saved with `request.user` as owner. Requires `Vehicle` with required owner.
- FR-06 — owners view and update only their own vehicles; URL tampering must not expose another owner's vehicle. Requires ownership structure supporting future `request.user` filtering.
- FR-07 — license-plate uniqueness and non-negative mileage with field errors. Requires normalized plate validation, case-insensitive database uniqueness, and mileage validation.
- FR-08 — owners view maintenance history filtered by vehicle ownership. Requires `MaintenanceRecord` linked to vehicle.
- FR-09 — administrators manage service types and maintenance intervals with persisting CRUD. Requires `ServiceType` with name, description, `interval_km`, `interval_months`, `duration_minutes`, price.
- FR-10 — technicians create maintenance records for assigned appointments; the record links vehicle, service, technician, mileage, and appointment. Requires `MaintenanceRecord` with all five relations.
- FR-11 — due and overdue maintenance computed from configured intervals and recorded history, returning service, status, last service, and reason. Requires intervals on `ServiceType` and history on `MaintenanceRecord`.
- FR-12 — owners view active service slots; only active slots with remaining capacity display. Requires `ServiceSlot` with active state and capacity.
- FR-13 — owners manually book appointments for their own vehicles stored against the selected slot. Requires `Appointment` linked to vehicle and slot.
- FR-14 — unavailable, full, expired, or duplicate slots rejected with a clear error and no appointment created. Requires slot integrity, capacity, and duplicate-active-booking rules.
- FR-15 — owners view and cancel eligible appointments; only cancellable statuses change. This plan defines stored status membership only; cancellation eligibility and behavior belong to a later workflow plan.
- FR-16 — technicians view only assigned appointments. Requires direct technician assignment on `Appointment`.
- FR-17 — technicians update status of assigned appointments; only valid transitions accepted. This plan defines stored status membership only; the transition graph and role-specific permissions belong to a later workflow/RBAC plan.
- FR-18 — administrators assign technicians to appointments. Requires nullable technician assignment set after booking.
- FR-19 — administrators manage spare-part records and quantities with persisting validated changes. Requires `SparePart` with part number, name, quantity, minimum stock, unit price.
- FR-20 — technicians record spare parts used during completed maintenance; usage stored through `MaintenancePart` with non-negative inventory. Requires explicit through model with positive quantity.
- FR-30 — atomic appointment booking. Requires constraints supporting later transactional booking.
- NFR-D01 — mileage and spare-part quantities never negative; database and form validation reject negatives.
- NFR-D02 — slot end time later than start time.
- NFR-D03 — slots never exceed configured capacity; concurrent or repeated booking cannot overfill.
- NFR-D04 — foreign-key deletion preserves valid history using PROTECT, CASCADE, or SET_NULL per business rules.
- NFR-M01 — separate accounts, vehicles, maintenance, appointments, inventory, and ai_agent responsibilities.
- NFR-R01 — atomic booking and inventory updates where multiple writes occur (future implementation; models must support it).
- Table 10 (SRS §6) relationship rows for User, Vehicle, TechnicianProfile, ServiceType, ServiceSlot, Appointment, MaintenanceRecord, SparePart, and MaintenancePart. AgentActionLog is recorded as a later AI audit task; Table 10 does not define an Appointment-to-MaintenanceRecord cardinality.
- Table 11 (SRS §6.2) entity attribute lists, keys, and constraints for all nine entities.
- SRS §6.3 rules: atomic capacity check before creation; owner immutable through owner-facing forms; protective or nullable history deletion; inventory rejects negative operations; prior-mileage discrepancy resolved by Administrator; AgentActionLog read-only to non-administrators.
- SRS §6.4 normalization: one subject per table; service and part data stored once and referenced; ServiceType separates reusable definitions; TechnicianProfile separates technician fields; MaintenancePart resolves the many-to-many with `quantity_used`; derived overdue data calculated, not duplicated.
- UJ-02 (add vehicle saved with `request.user`), UJ-04 (manual booking with server revalidation), UJ-07 (technician completion creates the maintenance record), UJ-09 (slot recheck inside transaction).
- SRS §9.5 step 4 (paragraph 168): implement vehicles, service types, slots, appointments, maintenance records, inventory, and admin registration.
- SRS §1.5.1 scope: vehicle registration and ownership-protected management; service types, maintenance records, recommended intervals, due-service evaluation; slots, booking, technician assignment, status updates; basic spare-parts inventory and parts-used recording.

## Current-State Analysis

Verified by read-only file inspection on 2026-09-25. No command was executed.

- `config/settings.py`: `INSTALLED_APPS` holds the six `django.contrib.*` apps plus `apps.authentication` only. `AUTH_USER_MODEL = 'authentication.User'`. PostgreSQL backend. No domain application is registered.
- `config/urls.py`: routes `admin/` and `accounts/` only. No domain URLs exist.
- `requirements.txt`: Django 6.1.1, `psycopg[binary]`, `python-dotenv`. No new dependency is proposed.
- `apps/authentication`: complete and frozen. Correct AppConfig name, approved `User` model with three roles and role check constraint, `CustomUserAdmin`, 65-test suite, applied `0001_initial` migration depending on `auth.0012_alter_user_first_name_max_length`.
- `apps/vehicle_management`: empty scaffolding. `apps.py` declares the incorrect `name = 'vehicle_management'` (importable path is `apps.vehicle_management`). `models.py`, `admin.py`, and `tests.py` are Django placeholder stubs. `migrations/` holds only `__init__.py`. No implementation exists.
- `apps/core`: stub with the same AppConfig name defect (`name = 'core'`). Placeholders only. Not in `INSTALLED_APPS`.
- `apps/ai_agent`: stub with the same AppConfig name defect (`name = 'ai_agent'`). Placeholders only. Not in `INSTALLED_APPS`.
- AGENTS.md theoretical applications (`accounts`, `vehicles`, `maintenance`, `appointments`, `inventory`, `ai_agent`) differ from actual packages; the SRS NFR-M01 application list governs placement in this plan.
- Baseline preserved: PostgreSQL only, secrets in untracked `.env`, approved User and authentication flow untouched, 65 tests passing, `check` passes, `makemigrations --check` reports no changes.

Missing files and applications accurately recorded: no `models.py` implementation, migration, admin registration, or test exists for any domain entity. No `vehicles`, `maintenance`, `appointments`, or `inventory` application exists. `apps/vehicle_management` and `apps/core` are unused legacy stubs.

## Authoritative Source and SRS Traceability

- Authoritative source is `docs/CARVIX_SRS_Group6.docx` (verified SHA-256 above), read through the complete 842-line extraction covering all 199 paragraphs and all 181 rows of the 19 tables.
- `docs/README.md` was read and used only to confirm the authoritative-document policy: the DOCX is authoritative, `docs/carvix-srs-v2.md` was removed as obsolete, and supporting files must not override the SRS.
- `docs/architecture.md`, `docs/erd.md`, `docs/user-journeys.md`, `AGENTS.md`, `.agents/README.md`, `.agents/PLAN_TEMPLATE.md`, and plans 000 through 003 were inspected for repository context only.
- Where supporting material conflicts with the DOCX, the DOCX governs. Recorded discrepancies: `docs/erd.md` uses roles `CLIENT | TECHNICIAN | MANAGER | ADMIN` plus `phone` and `avatar` on User (SRS Table 11 defines `OWNER | TECHNICIAN | ADMINISTRATOR` and exactly `id, username, email, password, role, is_active, date_joined`); supporting vehicle content adds VIN, fuel type, active flags, and `updated_at` (SRS Table 11 defines exactly `id, owner_id, manufacturer, model, model_year, license_plate, current_mileage, created_at`); supporting maintenance content adds `MAINTENANCE_TYPE.base_cost`, `interval_days`, `SERVICE_SLOT.technician_id`, `SERVICE_APPOINTMENT.created_by_id`, `PART_USAGE.unit_price` snapshots, and `FD-17/FD-18/FD-19`, `FR-NOT-01`, `FR-AUTH-06` identifiers; supporting journeys and architecture reference a Manager role, 13 tools, confirmation tokens, notifications, and chat tables absent from the SRS. None of these supporting-only items are included in this plan.
- The removed Markdown SRS, Git history, cached agent output, PLAN.pdf, and diagram images were not used as requirements sources.

## Existing Application Inventory

| Path | Inspection result |
| --- | --- |
| `apps/authentication/apps.py` | Correct; must not change. |
| `apps/authentication/models.py` | Approved `User`; must not change. |
| `apps/authentication/admin.py` | Approved admin; must not change. |
| `apps/authentication/tests.py` | 65 tests; must be preserved. |
| `apps/authentication/migrations/0001_initial.py` | Applied baseline; must not change. |
| `apps/vehicle_management/*` | Unused legacy stub with defective AppConfig name; untouched by this task. |
| `apps/core/*` | Unused legacy stub; untouched by this task. |
| `apps/ai_agent/*` | Stub reserved for the deferred AgentActionLog task; untouched by this task. |
| `config/settings.py` | Only `INSTALLED_APPS` registration changes. |
| `config/urls.py` | No change. |
| `requirements.txt`, `.env`, `.env.example` | No change. |

## Scope

Plan only: SRS-approved models with exact fields, relationships, constraints, indexes, validation, ordering, string behavior, and migration dependencies; model tests; minimal Admin registration; required application registration and AppConfig construction for new applications.

## Out-of-Scope Items

Authentication and profile changes, complete RBAC, permission decorators and mixins, ownership-protected endpoints, forms, views, URLs, templates, dashboards, vehicle CRUD workflows, manual booking flow, booking confirmation UI, cancellation flow, atomic booking implementation, row locking, race-condition services, inventory deduction and restoration, technician maintenance workflow, AgentActionLog implementation, agent tools, Chat UI, LLM integration, notifications, payments, maps, RAG, vector database, advanced reporting, frontend-framework installation, unrelated styling.

Supporting-only content remains excluded: CLIENT and MANAGER roles; VIN, fuel type, Vehicle active flag, and Vehicle `updated_at`; technician or service-type fields on ServiceSlot; Appointment `created_by`; MaintenancePart price snapshot; notifications; chat persistence tables; confirmation-token persistence; and supporting-only requirement identifiers.

## Domain Boundaries

- This task defines persistent structure only: tables, columns, relationships, constraints, indexes, model validation, and migration order.
- It defines no behavior: no views, forms, URLs, templates, permissions, transactions, services, tools, or interfaces.
- Structural foreign keys support future authorization without implementing it.
- Database constraints provide defense in depth without replacing backend authorization or transactional service logic.
- Repeating service and part data is stored once and referenced through foreign keys (SRS §6.4). Derived availability and overdue state are calculated later, never stored as uncontrolled duplicates.

## Model-by-Model Design

Conventions for every model: `settings.AUTH_USER_MODEL` for each user reference with no direct `User` import; explicit `related_name` on every relation; timezone-aware datetimes (`USE_TZ = True`); `DecimalField(max_digits=10, decimal_places=2)` for monetary values; strict database checks backing each NFR-D01/D02/D03 rule; safe `__str__` returning identifiers only, never secrets, hashes, tokens, or unnecessary personal data.

### Vehicle — `apps.vehicles`

SRS support: FR-05, FR-06, FR-07, FR-08, NFR-D01, NFR-D04, Table 10 User–Vehicle owns row, Table 11 Vehicle row, §6.3 owner-immutability rule, UJ-02.

- `owner = ForeignKey(settings.AUTH_USER_MODEL, on_delete=PROTECT, related_name="vehicles")`, required, no null or blank. Structural ownership; future Owner role expectation enforced at endpoints, not by this key. Account deactivation with `is_active=False` is preferred to deleting a user; deleting a referenced user must not remove the vehicle.
- `manufacturer = CharField(max_length=150)`, required.
- `model = CharField(max_length=150)`, required.
- `model_year = PositiveIntegerField()`, required. No minimum, maximum, current-year validator, or future-year margin is invented because the SRS states no year rule.
- `license_plate = CharField(max_length=32)`, required. Normalize by trimming surrounding whitespace and converting Latin letters to uppercase; preserve Arabic letters, digits, and meaningful internal separators without rewriting them. Add a named functional `UniqueConstraint(Lower("license_plate"))` so PostgreSQL enforces case-insensitive uniqueness in addition to normalization. Apply the same normalization during explicit model validation and in future ModelForms. No plain exact-match `unique=True` constraint is sufficient.
- `current_mileage = PositiveIntegerField()`, required, with database `CheckConstraint(current_mileage >= 0)` and matching model validation per FR-07 and NFR-D01.
- `created_at = DateTimeField(auto_now_add=True)`.
- Excluded with reasons: VIN, fuel type, active flags, and `updated_at` appear only in supporting material; SRS Table 11 defines neither them nor any rule requiring them.
- Ordering: `["-created_at", "-id"]`, supporting owner vehicle lists (UJ-02).
- String representation: license plate with manufacturer and model.
- Migration dependency: `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`.

### TechnicianProfile — `apps.maintenance`

SRS support: Table 10 User–TechnicianProfile has row, Table 11 TechnicianProfile row, §6.4 paragraph 90 separation rule, FR-16, FR-17, FR-18, RBAC §4.1 `technician__user` filtering rule.

- `user = OneToOneField(settings.AUTH_USER_MODEL, on_delete=PROTECT, related_name="technician_profile")`, required. One profile per user by construction. Account deactivation is preferred; deleting a referenced user must not silently remove the technician identity.
- `specialization = CharField(max_length=150)`, required, free text because the SRS defines no controlled vocabulary; trim surrounding whitespace.
- `is_available = BooleanField(default=True)`, required. The default is the schema-necessary value consistent with FR-18 assignment of available technicians.
- Technician-role expectation enforced in `clean()`: `user.role` must be `User.Role.TECHNICIAN` per Table 11. The relation, the validation, and future endpoint RBAC are three separate layers; the key alone guarantees nothing about role.
- Excluded with reasons: biography, phone, address, and profile image appear only in supporting material or not at all in the SRS.
- Ordering: `["id"]`.
- String representation: the related username with specialization.
- Migration dependency: `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`.

### ServiceType — `apps.maintenance`

SRS support: FR-09, FR-11, Table 10 ServiceType rows, Table 11 ServiceType row, §6.4 paragraph 91 reusable-definition rule, UJ-04, UJ-05.

- `name = CharField(max_length=150)`, required, stored stripped, with an explicitly named `UniqueConstraint` for unique service names.
- `description = TextField()`, required, matching the SRS attribute list.
- `interval_km = PositiveIntegerField()`, required, with database `CheckConstraint(interval_km > 0)` and matching validation. Drives FR-11 due evaluation with recorded history.
- `interval_months = PositiveIntegerField()`, required, with database `CheckConstraint(interval_months > 0)` and matching validation.
- `duration_minutes = PositiveIntegerField()`, required, with database `CheckConstraint(duration_minutes > 0)` and matching validation.
- `price = DecimalField(max_digits=10, decimal_places=2)`, required, with database `CheckConstraint(price >= 0)` and matching validation.
- Excluded with reasons: active flags and timestamps appear only in supporting material; Table 11 defines neither.
- Ordering: `["name"]`, supporting due-maintenance queries and admin lists.
- String representation: name only.
- Migration dependency: in the maintenance initial migration alongside TechnicianProfile; it has no User dependency itself.

### ServiceSlot — `apps.appointments`

SRS support: FR-12, FR-14, NFR-D02, NFR-D03, Table 10 ServiceSlot–Appointment row, Table 11 ServiceSlot row, UJ-04, UJ-09.

- `start_time = DateTimeField()`, required, timezone-aware.
- `end_time = DateTimeField()`, required, timezone-aware, with database `CheckConstraint(end_time > start_time)` and matching validation per NFR-D02.
- `capacity = PositiveIntegerField()`, required, with database `CheckConstraint(capacity > 0)` and matching validation per Table 11 and NFR-D03.
- `is_active = BooleanField(default=True)`, required. The default is the schema-necessary value consistent with FR-12 active-slot display.
- No technician relation is defined because SRS Table 11 lists no technician field on ServiceSlot; the supporting `technician_id` is a recorded discrepancy and is excluded. Technician assignment lives on Appointment per Table 11 and FR-18.
- No stored remaining capacity: availability is derived as capacity minus active bookings per §6.4 paragraph 92.
- Overlap prevention beyond the end-after-start invariant requires later model validation and transactional service logic; no overlap constraint is claimed here.
- Ordering: `["start_time", "id"]`, supporting active-slot queries (FR-12).
- Indexes: `start_time` per Table 11; composite `(is_active, start_time)` supporting active-slot queries.
- String representation: start and end times with capacity.
- Migration dependency: in the appointments initial migration.

### Appointment — `apps.appointments`

SRS support: FR-13, FR-14, FR-15, FR-16, FR-17, FR-18, FR-30, NFR-D03, NFR-D04, Table 10 Vehicle–Appointment, ServiceType–Appointment, ServiceSlot–Appointment, TechnicianProfile–Appointment rows, Table 11 Appointment row, UJ-04, UJ-07, UJ-09.

- `vehicle = ForeignKey("vehicles.Vehicle", on_delete=PROTECT, related_name="appointments")`, required.
- `service_type = ForeignKey("maintenance.ServiceType", on_delete=PROTECT, related_name="appointments")`, required, implementing Table 11 and §6.4 single-source service definitions.
- `slot = ForeignKey("appointments.ServiceSlot", on_delete=PROTECT, related_name="appointments")`, required, implementing FR-13 storage against the selected slot.
- `technician = ForeignKey("maintenance.TechnicianProfile", on_delete=PROTECT, related_name="appointments", null=True, blank=True)`, optional. Nullability is strictly necessary because FR-13 owner booking cannot assign a technician while FR-18 assigns one later through a separate administrator step.
- No direct owner field exists in Table 11; the owner derives from `vehicle.owner`.
- `status = CharField(max_length=20, choices=AppointmentStatus.choices, default=AppointmentStatus.PENDING)`, required, with a named database check limiting values to `PENDING`, `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, and `CANCELLED`. The active statuses for duplicate-booking protection are `PENDING`, `CONFIRMED`, and `IN_PROGRESS`; terminal statuses are `COMPLETED` and `CANCELLED`. This plan defines only vocabulary, default, database membership, and active classification. Transition graph, role-specific transition permission, cancellation eligibility/service, completion workflow, and endpoint authorization remain later workflow/RBAC work.
- `notes = TextField(blank=True, default="")`, optional. Optionality is strictly necessary so FR-13 booking and FR-10 completion succeed without forced free text.
- `booked_by_agent = BooleanField(default=False)`, required, distinguishing agent bookings under FR-25 and FR-26.
- `created_at = DateTimeField(auto_now_add=True)`.
- Duplicate-active-booking rule: named partial `UniqueConstraint(fields=["slot", "vehicle"], condition=status in PENDING, CONFIRMED, IN_PROGRESS)` per Table 11 and FR-14, preventing the same vehicle from holding two active bookings in one slot. COMPLETED and CANCELLED rows do not block a later otherwise-permitted booking under this rule. It does not enforce total slot capacity; NFR-D03 requires a later atomic transaction with suitable locking or equivalent concurrency control.
- Ordering: `["-created_at", "-id"]`.
- Indexes: composite `(slot, status)` for Table 11 slot/status queries. Django supplies the regular ForeignKey indexes for `slot` and `vehicle`; do not add duplicate explicit single-column indexes.
- String representation: appointment identifier with vehicle plate and slot start, without personal data.
- Migration dependencies: the vehicles and maintenance initial migrations.

### MaintenanceRecord — `apps.maintenance`

SRS support: FR-08, FR-10, FR-11, NFR-D01, NFR-D04, Table 10 Vehicle–MaintenanceRecord, ServiceType–MaintenanceRecord, TechnicianProfile–MaintenanceRecord rows, Table 11 MaintenanceRecord row, §6.3 history-deletion rule, UJ-03, UJ-07.

- `vehicle = ForeignKey("vehicles.Vehicle", on_delete=PROTECT, related_name="maintenance_records")`, required.
- `service_type = ForeignKey("maintenance.ServiceType", on_delete=PROTECT, related_name="maintenance_records")`, required.
- `technician = ForeignKey("maintenance.TechnicianProfile", on_delete=PROTECT, related_name="maintenance_records")`, required, implementing the FR-10 performer link.
- `appointment = ForeignKey("appointments.Appointment", on_delete=PROTECT, related_name="maintenance_records")`, required, implementing the FR-10 appointment link. Ad-hoc records without an appointment are not approved. Table 10 defines no Appointment-to-MaintenanceRecord cardinality and Table 11 defines a non-unique foreign key, so the schema permits multiple records per appointment; this does not assert that the workflow creates multiple records. A stricter workflow rule requires a later approved task.
- `service_date = DateField()`, required, with model validation rejecting future dates as strictly necessary for FR-10 completed-service semantics and FR-11 history-based due evaluation.
- `mileage_at_service = PositiveIntegerField()`, required, with database `CheckConstraint(mileage_at_service >= 0)` and matching validation per NFR-D01. The §6.3 prior-mileage Administrator-resolution workflow is future service logic, not a model constraint.
- `notes = TextField(blank=True, default="")`, optional, for the same strictly-necessary reason as appointment notes.
- Excluded with reasons: diagnostics, work-performed, and cost fields appear only in supporting material; Table 11 defines exactly the fields above.
- Ordering: `["-service_date", "-id"]`, supporting history and due-service queries (FR-08, FR-11, UJ-03).
- Indexes: composite `(vehicle, service_date)` for history queries plus Django's generated ForeignKey index for `service_type`, satisfying Table 11 without a duplicate standalone index.
- String representation: vehicle plate with service type and service date.
- Migration dependency: second maintenance migration depending on the maintenance initial migration and the vehicles, appointments, and inventory initial migrations, resolving the maintenance–appointments reference cycle without circular dependencies. Django controls generated migration filenames.

### SparePart — `apps.inventory`

SRS support: FR-19, FR-20, NFR-D01, Table 10 SparePart–MaintenancePart row, Table 11 SparePart row.

- `name = CharField(max_length=150)`, required, stored stripped.
- `part_number = CharField(max_length=100)`, required, stored stripped with an explicitly named `UniqueConstraint` for exact-match database uniqueness.
- `quantity = PositiveIntegerField()`, required, with database `CheckConstraint(quantity >= 0)` and matching validation per NFR-D01 and Table 11.
- `minimum_stock = PositiveIntegerField()`, required, with database `CheckConstraint(minimum_stock >= 0)` and matching validation per Table 11.
- `unit_price = DecimalField(max_digits=10, decimal_places=2)`, required, with database `CheckConstraint(unit_price >= 0)` and matching validation per Table 11.
- Excluded with reasons: descriptions, active flags, timestamps, reorder-level defaults beyond `minimum_stock`, and supplier data appear only in supporting material; Table 11 defines exactly the fields above with no defaults.
- Ordering: `["name", "id"]`.
- String representation: part number with name.
- Migration dependency: none beyond Django defaults.

### MaintenancePart — `apps.maintenance`

SRS support: FR-20, Table 10 MaintenanceRecord–MaintenancePart and SparePart–MaintenancePart rows, Table 11 MaintenancePart row, §6.4 paragraph 437 many-to-many resolution rule, UJ-07.

- `maintenance_record = ForeignKey("maintenance.MaintenanceRecord", on_delete=PROTECT, related_name="maintenance_parts")`, required.
- `spare_part = ForeignKey("inventory.SparePart", on_delete=PROTECT, related_name="maintenance_parts")`, required.
- `quantity_used = PositiveIntegerField()`, required, with database `CheckConstraint(quantity_used > 0)` and matching validation per Table 11 and FR-20.
- Pair uniqueness: `UniqueConstraint(fields=["maintenance_record", "spare_part"])` per Table 11.
- Excluded with reasons: unit-price snapshots and timestamps appear only in supporting material; Table 11 defines exactly the fields above. Stock deduction stays a future atomic task.
- Ordering: `["id"]`.
- String representation: record identifier with part number and quantity.
- Migration dependency: same second maintenance migration as MaintenanceRecord.

## Relationship Analysis

- `Vehicle.owner` is structural ownership supporting FR-05, FR-06, and FR-08; future queries filter by `request.user`.
- `TechnicianProfile.user` is a one-to-one extension validated against the Technician role; RBAC §4.1 `technician__user` filtering applies later through `Appointment.technician` and `MaintenanceRecord.technician`.
- `Appointment` carries direct `vehicle`, `service_type`, `slot`, and nullable `technician` references exactly as Table 11 specifies; the owner derives from the vehicle with no duplication.
- `MaintenanceRecord` carries direct `vehicle`, `service_type`, `technician`, and `appointment` references exactly as Table 11 and FR-10 specify.
- `MaintenancePart` resolves the record–part many-to-many with the relationship-specific `quantity_used` attribute exactly as §6.4 requires.
- Every user reference uses `settings.AUTH_USER_MODEL`; no direct `User` import appears in domain models.

## Deletion Behavior

- `PROTECT` applies to every domain relationship: `Vehicle.owner`; `TechnicianProfile.user`; `Appointment.vehicle`, `service_type`, `slot`, and `technician`; `MaintenanceRecord.vehicle`, `service_type`, `technician`, and `appointment`; and `MaintenancePart.maintenance_record` and `spare_part`.
- No `CASCADE` or `SET_NULL` deletion behavior is used. `Appointment.technician` remains nullable only to represent a not-yet-assigned appointment; a referenced technician cannot be deleted.
- Account deactivation with `is_active=False` is preferred to destructive deletion. Any future destructive cleanup must be a separately approved administrative operation.
- These choices preserve vehicles, technician identity, bookings, assignments, maintenance history, and parts usage, consistent with NFR-D04 and §6.3.

## Constraint Strategy

- Every `CheckConstraint` and `UniqueConstraint` has an explicit stable, concise application-prefixed name that fits PostgreSQL's identifier limit; no anonymous constraints. Names include `vehicles_plate_ci_uniq`, `vehicles_mileage_gte_0`, `maintenance_service_name_uniq`, `maintenance_interval_km_gt_0`, `maintenance_interval_months_gt_0`, `maintenance_duration_gt_0`, `maintenance_price_gte_0`, `appointments_slot_end_gt_start`, `appointments_slot_capacity_gt_0`, `appointments_status_valid`, `appointments_active_slot_vehicle_uniq`, `inventory_part_number_uniq`, `inventory_part_quantity_gte_0`, `inventory_min_stock_gte_0`, `inventory_unit_price_gte_0`, `maintenance_record_mileage_gte_0`, `maintenance_part_quantity_gt_0`, and `maintenance_record_part_uniq`.
- Unique constraints: named functional case-insensitive `Lower("license_plate")`; named uniqueness for `ServiceType.name` and `SparePart.part_number`; named `MaintenancePart` record-plus-part pair; and a named partial unique on `Appointment(slot, vehicle)` for statuses `PENDING`, `CONFIRMED`, and `IN_PROGRESS`.
- Check constraints: `current_mileage >= 0` and `mileage_at_service >= 0` (NFR-D01); `end_time > start_time` (NFR-D02); `capacity > 0` (Table 11, NFR-D03); `interval_km`, `interval_months`, `duration_minutes > 0` (Table 11); `price`, `unit_price`, `quantity`, `minimum_stock >= 0` (Table 11, NFR-D01, FR-20); `quantity_used > 0` (Table 11, FR-20); and Appointment status membership (Table 11). User role membership is already constrained by the existing User model.
- Overlap prevention, capacity counting, duplicate rechecking, prior-mileage reconciliation, and future-date handling beyond the service-date validator remain model validation plus future transactional service logic.

## Index Strategy

- Unique indexes are generated by named `UniqueConstraint` definitions, including the functional plate constraint and partial active-booking constraint; do not use unnamed constraint declarations.
- Retain explicit `ServiceSlot.start_time` as required by Table 11 and composite `(is_active, start_time)` for active-slot queries.
- Retain `Appointment(slot, status)` for Table 11 slot/status queries and `MaintenanceRecord(vehicle, service_date)` for history queries. Django-generated ForeignKey indexes cover the relevant single-column references, including Appointment slot/vehicle and MaintenanceRecord service type.
- Do not create duplicate explicit single-column indexes for normal ForeignKey fields or for fields already covered by an appropriate index. Django-generated indexes from ForeignKey and uniqueness definitions remain.

## Validation Strategy

- `Model.save()` does not call `full_clean()` automatically. `Model.clean()` provides domain validation only when validation is explicitly invoked; tests for model validation must call `full_clean()`.
- Explicit model validation covers plate normalization, choices, strict positivity, end-after-start, future service-date rejection, technician-role profile validation, and relationship consistency. Future ModelForms must apply the same plate normalization and provide field-specific errors per FR-07.
- Named database constraints separately enforce supported invariants for direct ORM writes and relevant bulk paths; PostgreSQL constraint tests must exercise database enforcement separately from `full_clean()` tests.
- Model validation and database constraints do not replace endpoint authorization or ownership checks.
- Normalization trims surrounding whitespace on manufacturer, model, names, part numbers, specialization, service names, and license plates. License plates additionally uppercase Latin letters while preserving Arabic letters, digits, and internal separators. Plate uniqueness is case-insensitive at the PostgreSQL level through the functional constraint; no case-insensitive behavior is otherwise inferred for part numbers.

## Historical-Data Strategy

- Appointments, maintenance records, and parts usage are historical once created and are shielded by `PROTECT` on every referenced row.
- Timestamps exist exactly where Table 11 defines them: `Vehicle.created_at`, `Appointment.created_at`. No other domain timestamp is added.
- No soft deletion and no snapshots are introduced; §6.3 allows protective or nullable policies and this plan selects protective throughout.

## Ownership and RBAC Boundary

- `Vehicle.owner` represents structural ownership and is protected from User deletion; deactivate accounts with `is_active=False` instead.
- `request.user` remains the future authenticated identity source.
- Future forms must not expose trusted owner assignment.
- Future views must not trust submitted owner IDs.
- Future Owner queries must filter by `request.user`.
- Future Technician operations must validate appointment assignment.
- Administrator permissions remain a later task.
- Hiding UI controls is not authorization.
- Backend authorization remains mandatory.
- Foreign keys do not replace permission checks.
- Model validation does not replace endpoint authorization.
- No permission decorators, role mixins, forms, views, URLs, or templates are added in this task.

## Booking and Concurrency Boundary

- Structures added for booking: slot integrity check, positive capacity, active state, derived availability, partial unique duplicate-active-booking constraint, and bookable references on `Appointment`.
- Reserved for later: owned-vehicle selection, service choice, active-slot queries, booking summary, explicit confirmation, availability rechecking, `transaction.atomic()`, row locking, capacity updates, duplicate checks, conflict handling, cancellation, RBAC, and ownership enforcement.
- The active duplicate-booking set is `PENDING`, `CONFIRMED`, and `IN_PROGRESS`; `COMPLETED` and `CANCELLED` do not block a later permitted booking under this constraint.
- The partial unique constraint prevents duplicate active bookings for one vehicle and one slot. It does not enforce total slot capacity. Capacity counting needs a later atomic transaction with appropriate locking or equivalent concurrency control per NFR-D03, §6.3, and UJ-09.
- Booking workflow, transition rules, role permissions, cancellation, and endpoint authorization remain outside this model task.

## Inventory Boundary

- Added fields with constraints: `quantity`, `minimum_stock`, `unit_price` on `SparePart`; `quantity_used` on `MaintenancePart`.
- Reserved for later: atomic stock deduction and restoration, row locking, insufficient-stock handling, maintenance-completion integration, and transaction rollback under NFR-R01 and §6.3 inventory rules.

## AgentActionLog Boundary

- FR-31 requires an `AgentActionLog` for each AI-tool attempt; FR-35 allows authorized Administrator inspection; NFR-R03 requires auditability. The SRS defines its fields and User relationship in Table 10/Table 11, and §6.3 requires non-administrator read restriction.
- Defer implementation to a dedicated AI audit and logging task in `apps.ai_agent`. Traditional domain models do not depend on AgentActionLog and support manual workflows without it.

## Django Admin Scope

Minimal registration for each included model in its owning application: basic `list_display`, `search_fields`, `list_filter`, ordering, and read-only `created_at` where the SRS defines it. No complex workflows. Admin is never a substitute for future Owner, Technician, or Administrator endpoints.

## Expected Files

New applications to create (each with `__init__.py`, corrected `apps.py`, `models.py`, `admin.py`, `tests.py`, `migrations/__init__.py`):

- `apps/vehicles/*` — Vehicle and its tests, admin, and migrations.
- `apps/maintenance/*` — ServiceType, TechnicianProfile, MaintenanceRecord, MaintenancePart with tests, admin, and two migrations.
- `apps/appointments/*` — ServiceSlot and Appointment with tests, admin, and migrations.
- `apps/inventory/*` — SparePart with tests, admin, and migrations.

Files expected to be modified after approval:

- `config/settings.py` — add `apps.vehicles`, `apps.maintenance`, `apps.appointments`, `apps.inventory` to `INSTALLED_APPS` only.
- `.agents/plans/004-core-domain-models.md` — this plan.

Expected migrations are described by application, ordering, contents, and dependencies in Migration Plan. Django controls final generated filenames; no exact generated filename is promised.

Files that must not change: `apps/authentication/models.py`, `apps/authentication/migrations/`, `apps/authentication/forms.py`, `apps/authentication/views.py`, `apps/authentication/urls.py`, authentication templates, `config/urls.py`, `.env`, `.env.example`, `requirements.txt`, `apps/vehicle_management/*`, `apps/core/*`, `apps/ai_agent/*`.

## Application Placement

NFR-M01 requires separation of accounts, vehicles, maintenance, appointments, inventory, and ai_agent responsibilities, so convenience placement of every model in `apps.vehicle_management` is rejected.

- `apps.vehicles` holds Vehicle under FR-05 through FR-08 and UJ-02/UJ-03 ownership workflows.
- `apps.maintenance` holds ServiceType, TechnicianProfile, MaintenanceRecord, and MaintenancePart under FR-09, FR-10, FR-11, FR-20, UJ-03, UJ-05, and UJ-07 service, technician, history, and parts-usage workflows. TechnicianProfile sits here rather than in authentication because that application is frozen and §6.4 separates technician fields for maintenance operations.
- `apps.appointments` holds ServiceSlot and Appointment under FR-12 through FR-18 and UJ-04/UJ-09 scheduling, booking, assignment, and status workflows.
- `apps.inventory` holds SparePart under FR-19 catalog and quantity workflows.
- `apps.ai_agent` is reserved for a later dedicated AgentActionLog implementation, required by FR-31/FR-35/NFR-R03 but independent of traditional domain models.
- New AppConfigs use the correct dotted names `apps.vehicles`, `apps.maintenance`, `apps.appointments`, and `apps.inventory`, following the verified authentication pattern. The defective legacy names in `apps/vehicle_management`, `apps/core`, and `apps/ai_agent` are recorded without modification. Cleanup of these legacy stubs is a separate repository-maintenance task; this plan neither modifies nor repurposes them.

## Alternatives Considered

- One application versus SRS-required domain separation: separation chosen per NFR-M01; a single application would violate the cited maintainability requirement.
- Separate TechnicianProfile versus User role only: profile chosen per Table 10, Table 11, §6.4 paragraph 90, and FR-16 through FR-18 assignment needs.
- Separate ServiceSlot versus appointment datetime: slot chosen per FR-12, FR-14, NFR-D02, NFR-D03, Table 10, Table 11, UJ-04, and UJ-09.
- Storing Appointment owner versus deriving from Vehicle: derivation chosen; Table 11 defines no owner field and §6.4 forbids uncontrolled duplication.
- Direct technician assignment versus derivation from ServiceSlot: direct assignment chosen; Table 11 defines `technician_id` on Appointment and FR-18 assigns technicians to appointments, while the slot carries no technician field.
- Required versus nullable appointment on MaintenanceRecord: required chosen; FR-10 links each record to an appointment and the SRS approves no ad-hoc variant.
- Explicit MaintenancePart through model versus direct many-to-many: explicit through chosen per Table 10, Table 11, §6.4 paragraph 437, and FR-20.
- CASCADE versus PROTECT versus SET_NULL: PROTECT for every domain relationship; user accounts are deactivated rather than destructively deleted. No CASCADE or SET_NULL is used, per NFR-D04 and §6.3.
- Exact-match versus case-insensitive plate uniqueness: normalized Latin-uppercase input plus named PostgreSQL functional uniqueness on `Lower("license_plate")`, with explicit model validation and future ModelForm normalization, ensures equivalent plates cannot coexist.
- `MaintenanceRecord.appointment` one-to-one versus foreign key: required ForeignKey is chosen because Table 10 defines no cardinality and Table 11 provides no uniqueness rule; a later workflow may add a restriction only through an approved task.
- Appointment status transitions in this task versus a later workflow: this task stores the approved vocabulary/default and classifies active statuses for the partial unique constraint; transition and role rules remain later work.
- Database constraint versus service-layer validation: both as defense in depth, each rule assigned to the layer that enforces it.
- Stored remaining capacity versus derived remaining capacity: derived, per §6.4 paragraph 92.

## Recommended Approach

Create the four SRS-named domain applications with the eight SRS-defined models exactly as specified above, register them in `INSTALLED_APPS`, generate migrations in the dependency order below, add model tests and minimal admin registration, and defer AgentActionLog. Use protected domain relationships, named database constraints, normalized case-insensitive plate uniqueness, and only justified explicit indexes. This satisfies FR-05 through FR-20 structural needs, NFR-D01 through NFR-D04, NFR-M01 separation, §6 normalization and integrity rules, and §9.5 step 4 with the smallest compliant footprint.

## Implementation Steps

The plan is approved for implementation. Implementation must remain within the approved scope and must follow the migration, human-review, PostgreSQL, and testing gates defined in this plan.

1. Create `apps/vehicles`, `apps/maintenance`, `apps/appointments`, and `apps/inventory` with correct AppConfigs, models, admin, tests, and migrations packages.
2. Implement the eight models exactly as specified, with `related_name` values, `on_delete` behavior, constraints, indexes, ordering, validation, and safe `__str__` methods.
3. Register the four applications in `INSTALLED_APPS`.
4. Add minimal Admin registration per application.
5. Add model tests per the Test Plan without touching the 65 existing tests.
6. Run `python manage.py check` and expect no issues.
7. Generate migrations for the approved applications and manually inspect every generated migration; use `migrations.swappable_dependency(settings.AUTH_USER_MODEL)` for User references.
8. Verify Table 11 fields, relationships, defaults, choices, named constraints, indexes, and dependencies in each migration. Django determines final migration filenames.
9. Run `python manage.py makemigrations --check` and expect no changes.
10. Obtain human approval before any persistent-database migration.
11. Run `python manage.py migrate` only after approval.
12. Run `python manage.py showmigrations` to confirm applied state.
13. Run application tests on PostgreSQL.
14. Run the complete project suite on PostgreSQL with no SQLite fallback.
15. Report per AGENTS.md §13 and mark IMPLEMENTED only after implementation and required tests are complete.

## Migration Plan

1. Run `python manage.py check`.
2. Create the vehicles initial migration for Vehicle, using `migrations.swappable_dependency(settings.AUTH_USER_MODEL)` for its User reference.
3. Create the inventory initial migration for SparePart; it has no domain-model dependency.
4. Create the maintenance initial migration containing TechnicianProfile and ServiceType. Use the swappable User dependency for TechnicianProfile; do not add speculative auth/contenttypes dependencies.
5. Create the appointments initial migration containing ServiceSlot and Appointment, depending on the vehicles and maintenance initial migrations.
6. Create a second maintenance migration containing MaintenanceRecord and MaintenancePart, depending on maintenance's initial migration and the vehicles, appointments, and inventory initial migrations. This order avoids a circular dependency.
7. Django determines the final generated migration filenames. Inspect each migration and verify fields, relationships, defaults, choices, named constraints, indexes, and dependencies.
8. Run `python manage.py makemigrations --check`; obtain human approval before persistent-database migration; then apply migrations and confirm applied state.
9. Run application tests and the complete project suite on PostgreSQL, including separate model `full_clean()` and database-constraint checks. No SQLite fallback.
10. No migration is created during planning; no `makemigrations` or `migrate` runs in this plan-correction task.

## Test Plan

Preserve all 65 existing tests. Add model tests per included model covering valid creation, required and optional fields, defaults, choices, relationships, reverse relationships, uniqueness, named check constraints, model validation via explicit `full_clean()`, PostgreSQL database enforcement, deletion behavior, historical preservation, ordering, and safe string representation. Test PostgreSQL constraints separately from model validation; neither layer substitutes for endpoint authorization.

### Vehicle

Owner relationship and reverse accessor; trimming and Latin-uppercase plate normalization while preserving Arabic letters, digits, and internal separators; case-insensitive database uniqueness proving `ABC-123` and `abc-123` cannot coexist; non-negative mileage acceptance and negative rejection at model and database levels; required fields; owner deletion blocked by `PROTECT`; ordering and string output.

### TechnicianProfile

One profile per user with duplicate rejection, technician-role acceptance, non-technician rejection when `full_clean()` invokes `clean()`, `is_available` default, user deletion blocked by `PROTECT`, blocked deletion while appointments or records reference the profile, and string output.

### ServiceType

Valid creation with all six SRS attributes, unique name rejection, positive interval and duration enforcement with zero rejection, non-negative price enforcement, required-field rejection, PROTECT deletion while referenced, name ordering, and string output.

### ServiceSlot

Technician-free creation per Table 11, timezone-aware values, end-after-start acceptance and inversion rejection via explicit `full_clean()` and at the database level, positive capacity with zero rejection, active-state default and filtering, deletion blocked while appointments reference the slot, and string output.

### Appointment

Required vehicle, service type, and slot relations with reverse accessors; nullable technician with later assignment; the five approved statuses, `PENDING` default, and status membership check; active statuses `PENDING`, `CONFIRMED`, and `IN_PROGRESS`; invalid-status rejection; duplicate-active `(slot, vehicle)` rejection at the database level; exclusion of `COMPLETED` and `CANCELLED` from that partial constraint; relationship consistency; `PROTECT` deletion on every relation; explicit `full_clean()` model validation. Do not test transition, cancellation, or endpoint-permission behavior in this model task.

### MaintenanceRecord

Required vehicle, service type, technician, and appointment ForeignKey relations; verify the appointment relation is not unique and permits multiple MaintenanceRecord rows; future service-date rejection via explicit validation; non-negative mileage at service at both levels; history preservation through `PROTECT` on every relation; vehicle and date ordering; relationship consistency; and string output.

### SparePart

Valid creation with all five SRS attributes, unique part-number rejection, non-negative quantity, minimum stock, and unit price at both levels, required-field rejection, PROTECT deletion while referenced by parts usage, name ordering, and string output.

### MaintenancePart

Valid record-plus-part relation with reverse accessors, positive quantity with zero rejection at both levels, duplicate pair rejection, PROTECT deletion on both relations, and PostgreSQL constraint enforcement.

### System validation

All existing 65 tests, all new application-model tests, complete project-suite execution, `python manage.py check`, `python manage.py makemigrations --check`, PostgreSQL testing, explicit `full_clean()` validation tests, and separate PostgreSQL database-constraint tests. Verify named constraint presence and functional case-insensitive plate uniqueness. No final test count is invented.

## Security Analysis

- Future mass assignment: owner, technician, creator-equivalent, and privilege-adjacent relations are server-assigned and validated; §6.3 already bars owner changes through owner-facing forms.
- `request.user` identity binding: ownership derives from `vehicle.owner` matched against the authenticated user in later views and tools per FR-05, FR-06, UJ-02, and §8 boundaries.
- IDOR: FR-06 URL-tampering resistance and RBAC §4.1 ownership filtering are future view requirements supported by the owner chain.
- Invalid role relationships: profile creation validates the Technician role; keys alone prove nothing.
- Unauthorized foreign-key assignment: vehicle, slot, service, technician, and parts relations require future ownership and assignment checks per FR-16 through FR-20 and RBAC Table 6.
- Relationship tampering: appointment and record consistency across vehicle, slot, service, technician, and appointment is validated at model level with backend authorization later.
- Destructive User deletion: `PROTECT` on Vehicle.owner and TechnicianProfile.user prevents silent loss of vehicles or technician identity; account deactivation is preferred.
- Historical-data loss: `PROTECT` applies to every domain relationship; no domain relationship uses `CASCADE` or `SET_NULL`.
- Plate collisions: normalization and a named PostgreSQL functional `Lower` uniqueness constraint prevent equivalent Latin-case plate values from coexisting; explicit model and future form normalization provide consistent user-facing behavior.
- Double booking: named partial unique active-booking constraint plus future transactional rechecks under FR-14, FR-30, and UJ-09.
- Slot-capacity concurrency: the partial unique constraint does not enforce total capacity; NFR-D03 requires counting inside a later atomic transaction with suitable concurrency control.
- Duplicate active bookings: same-vehicle same-slot actives rejected at the database level.
- Negative stock, invalid used quantity, invalid mileage, and missing model-year rules: constrained per NFR-D01, Table 11, FR-07, and FR-20.
- Sensitive information in `__str__`: identifiers only.
- Database constraints provide defense in depth for supported direct ORM and relevant bulk write paths. `save()` does not invoke `full_clean()`; explicit model validation does not replace database constraints or endpoint authorization.
- Future backend authorization remains mandatory per RBAC §4 and §8 boundaries.
- Safe migration defaults with no destructive data migration.
- No unnecessary personal data beyond SRS attributes; secrets and environment safety unchanged with no new variables.

## Rollback and Failure Handling

- Before any persistent migration: delete generated migration files and reverse unapplied model, admin, and test changes. Never reverse `authentication.0001_initial`.
- After migration: use a human-approved backward migration; no automatic data deletion.
- On validation failure: stop, correct the model or test, regenerate and reinspect migrations, rerun `check`, `makemigrations --check`, explicit `full_clean()` tests, PostgreSQL constraint tests, and the full PostgreSQL suite.
- On PostgreSQL unavailability: stop and report blocked; never substitute SQLite.
- Resolved model decisions are recorded below. Any newly discovered conflict with the authoritative SRS must be documented and brought for a decision before changing this plan or implementation.

## Definition of Done

- Every model and field traces to a cited SRS section, table, FR, NFR, or journey.
- Models, migrations, tests, and minimal admin are complete.
- All 65 existing tests pass unchanged.
- New model tests pass on PostgreSQL.
- The complete suite passes on PostgreSQL.
- `check` passes and `makemigrations --check` reports no changes.
- No SQLite fallback was used.
- No secrets or private data were committed.
- User and historical domain references use the approved `PROTECT` policies; endpoint authorization remains mandatory.
- Authentication, URLs, templates, environment, requirements, and legacy stubs changed only as listed.
- A teammate can explain and reproduce the change.

## Open Questions

None blocking.

Approved decisions:

- Appointment status vocabulary is approved for storage and duplicate-booking classification; transition, role, cancellation, and completion workflow rules remain later work.
- License plates use surrounding-whitespace trimming, Latin-uppercase normalization, preservation of Arabic letters, digits, and internal separators, and case-insensitive PostgreSQL uniqueness via a named functional `Lower` constraint.
- Technician specialization remains free text.
- `Vehicle.model_year` remains a `PositiveIntegerField` with no invented range or validator.
- Supporting-only roles, fields, and features remain excluded.
- `MaintenanceRecord.appointment` remains a required ForeignKey because the SRS defines no one-to-one uniqueness.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-25

The plan is approved for implementation. Implementation must remain within the approved scope and must follow the migration, human-review, PostgreSQL, and testing gates defined in this plan.

## Implementation Report

- **Summary:** Implemented the eight approved core domain models and fields from SRS Table 11 in their approved applications: `Vehicle` (`apps.vehicles`); `TechnicianProfile`, `ServiceType`, `MaintenanceRecord`, and `MaintenancePart` (`apps.maintenance`); `ServiceSlot` and `Appointment` (`apps.appointments`); and `SparePart` (`apps.inventory`). Added the approved relationships, `PROTECT` deletion behavior, related names, ordering and string representations, text and license-plate normalization, case-insensitive PostgreSQL plate uniqueness, appointment status choices, partial uniqueness for active duplicate bookings, named constraints and indexes, model validation, minimal Django Admin registration, and the application settings entries. `AgentActionLog` remains deferred to its dedicated task in `apps.ai_agent`.
- **Files changed:** Added the four app packages and their model, admin, test, and migration files; updated `config/settings.py` to register the apps; and updated this plan report. No unrelated files were changed.
- **Tests executed:** `python manage.py check`; `python manage.py makemigrations --check`; `python manage.py test apps.vehicles apps.inventory apps.maintenance apps.appointments -v 2`; `python manage.py test -v 2`; and `git diff --check`. Migration application and `showmigrations` were also checked against PostgreSQL.
- **Test results:** Django system check reported no issues; `makemigrations --check` reported no changes; all 53 core-domain tests passed; all 118 project tests passed with 0 failures and 0 skipped; `git diff --check` passed; and all listed migrations were applied. Tests used PostgreSQL, not SQLite.
- **Migration/environment changes:** Generated and applied `apps/vehicles/migrations/0001_initial.py`, `apps/inventory/migrations/0001_initial.py`, `apps/appointments/migrations/0001_initial.py`, `apps/maintenance/migrations/0001_initial.py`, and `apps/appointments/migrations/0002_initial.py`. The migrations use the swappable dependency for the custom User; the auth migration was unchanged. The resulting dependency/application order was `vehicles.0001_initial`, `inventory.0001_initial`, `appointments.0001_initial`, `maintenance.0001_initial`, then `appointments.0002_initial`. No environment variables or secrets were changed.
- **Security checks:** `Vehicle.owner` and the listed domain relationships use `PROTECT`; ownership remains structurally represented by the vehicle relationship, while endpoint authorization and RBAC remain application responsibilities. Database constraints provide integrity checks but do not replace authorization. No secrets were added, and the deferred AI logging model was not introduced.
- **Review fixes:** Four test modules initially failed to import because `skipIf` was imported from `django.test`; the imports were corrected to use Python's `unittest`, and the affected tests were rerun. A vehicle required-fields test also expected an owner error while supplying a valid owner; its expected field set was corrected. Both fixes were followed by the individual/core and full-suite runs recorded above and required no model or migration changes.
- **Remaining risks:** Slot-capacity enforcement still requires transactional concurrency control; inventory quantity changes require atomic transaction handling; constraints do not replace endpoint authorization; and appointment status transitions remain part of a later workflow task.
- **Deviations from plan:** Django generated a split migration sequence (`appointments.0001_initial`, `maintenance.0001_initial`, and `appointments.0002_initial`) rather than the anticipated possible second maintenance migration. Only migration filenames and dependency order differed; model semantics and approved decisions did not. Future vehicle CRUD, RBAC and ownership enforcement, manual booking and capacity handling, status transitions and cancellation, technician workflow, maintenance completion, atomic inventory deduction/restoration, role dashboards, `AgentActionLog`, and AI tools/chat/LLM remain outside this implementation phase.
- **Result:** Implementation and required checks are complete with no blockers. The changes are ready for human diff review and pull-request preparation.
