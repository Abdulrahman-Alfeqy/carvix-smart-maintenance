# Local Demo Seed Data

`python manage.py seed_demo_data` creates or refreshes a deterministic CARVIX demo dataset using the existing PostgreSQL schema. It does not flush the database, delete records, or modify non-demo identities. Reserved demo identity collisions stop the command rather than overwriting unrelated data.

The dataset includes two Owners, two Technicians with matching TechnicianProfiles, one Administrator, multiple owner-separated Vehicles, four ServiceTypes, active future and inactive historical ServiceSlots, manual pending bookings, completed historical Appointment/MaintenanceRecord pairs, SpareParts, and MaintenancePart usage examples. Maintenance status remains calculated by the existing due-service logic; the seed command does not store due statuses or decrement inventory.

Demo usernames are `demo.owner.one`, `demo.owner.two`, `demo.technician.one`, `demo.technician.two`, and `demo.administrator`. By default, seeded accounts have unusable passwords. To enable local sign-in, set `CARVIX_DEMO_PASSWORD` in the command process environment before running the command. Choose a local-only password; do not commit it, put it in source control, or use it in production. The command never prints the password.

The command can be run repeatedly. Demo-owned records are identified by reserved usernames, vehicle plates, service descriptions, part numbers, or seed markers in existing appointment/maintenance notes. ServiceSlots do not have a seed marker in the current model; the command locates their seeded slots through the tagged Appointments and refuses ambiguous unmarked slot collisions. Slots used by non-demo Appointments are not shifted during refresh.

Historical completed Appointments exist only to satisfy the current required MaintenanceRecord relationships and provide maintenance-history examples. They are static demonstration records, not records produced by a Technician completion workflow. Pending future bookings are created through the existing booking service. The command does not implement Technician assignment or status transitions, inventory mutation, cancellation, AI, or other workflows.
