# CARVIX 15-Minute Demo Runbook

This runbook demonstrates existing CARVIX workflows in a local environment. Follow the SRS at [`CARVIX_SRS_Group6.docx`](CARVIX_SRS_Group6.docx) as the source of requirements. Do not present a planned, deferred, or unverified feature as implemented.

## Before the demo

1. Use a local PostgreSQL database and configure `.env` from `.env.example`; do not use a shared or production database.
2. Install dependencies, apply migrations, and prepare demo records:

   ```powershell
   python -m pip install -r requirements.txt
   python manage.py migrate
   python manage.py seed_demo_data
   python manage.py runserver
   ```

3. Seeded usernames are `demo.owner.one`, `demo.owner.two`, `demo.technician.one`, `demo.technician.two`, and `demo.administrator`. Their passwords are unusable by default. For local sign-in only, set `CARVIX_DEMO_PASSWORD` to a one-time local password in the process environment before running the seed command, then remove it. Never commit, display, or reuse that password. Full seed details and limitations are in [`demo-seed-data.md`](demo-seed-data.md).
4. Check the records beforehand: the seed command is idempotent, but appointments and slots can change as the demo proceeds. Choose a future slot with remaining capacity for the manual booking portion.
5. Prepare an authorized Django Admin account separately if you intend to inspect AgentActionLog. The account must be a Django staff user, have domain role `ADMINISTRATOR`, and have the `view_agentactionlog` permission. A seeded Administrator role alone does not grant Django Admin access.
6. Open the app at `http://127.0.0.1:8000/`. Do not show `.env`, password fields, database credentials, private browser autofill, or real user data in screenshots or screen sharing.

## Timed demo sequence (15 minutes)

| Time | Role and action | What to show |
| --- | --- | --- |
| 0:00–1:00 | Introduction | CARVIX's vehicle-maintenance scope, three roles, PostgreSQL/Django architecture, and the authoritative SRS. State that the demo uses a local seeded dataset. |
| 1:00–2:00 | Owner sign-in | Sign in as a demo Owner and show the role-aware profile entry points. Do not expose the password. |
| 2:00–4:00 | Owner vehicles | Open Vehicles, select an owned vehicle, and show its details, maintenance history, and calculated due-service overview. Explain that history is scoped to the signed-in Owner. |
| 4:00–7:00 | Manual booking | From the owned Vehicle page, choose a service and a displayed future slot with capacity. Submit the explicit booking action and show the saved appointment confirmation. |
| 7:00–8:00 | Owner appointments | Open the Owner appointment list and a booking's detail page. Emphasize that appointment records shown belong to the Owner's vehicles. |
| 8:00–9:00 | Administrator assignment | Sign in as an authorized domain Administrator and open Technician Assignments. Assign the new pending appointment to an available Technician. If none is suitable, use an unassigned demo appointment. |
| 9:00–12:00 | Technician workflow | Sign in as the assigned Technician, open only the assigned appointment, start service, and complete maintenance with valid mileage and (optionally) a seeded spare part. Show the success result. |
| 12:00–13:00 | Owner history | Return to the Owner's vehicle and show the new maintenance record in its history. Explain that due-service information is calculated from the configured intervals and history. |
| 13:00–14:00 | Administrator activity inspection | Open Django Admin at `/admin/ai_agent/agentactionlog/` using the authorized account. Show only records that actually exist. The list may be empty until an approved workflow generates AgentActionLog rows; do not fabricate entries or describe the empty state as a failure. |
| 14:00–15:00 | Close and traceability | Show the README, this runbook, authoritative SRS, and supporting ERD/architecture references. Summarize verified workflows and clearly identify any deferred capability. |

### Flow order and account switching

The flow is intentionally ordered Owner → Administrator → Technician → Owner so the appointment is created before assignment, and completed maintenance can then be seen in the same Owner's history. Log out using the application control before switching accounts. If a page or dataset differs from the expected state, explain the actual behavior rather than changing data during the presentation.

Historical completed appointments inserted by the seed command are static records needed for maintenance-history examples. They were not produced by the Technician completion workflow. The command also does not implement assignment, status transitions, or inventory deduction.

## SRS traceability checklist

| Demo evidence | SRS references | Check |
| --- | --- | --- |
| Owner registration/sign-in and role-aware entry points | FR-01–04; UJ-01; NFR-S01–02 | ☐ |
| Owner vehicle list/detail and ownership-protected update | FR-05–07; UJ-02; NFR-S03–04 | ☐ |
| Maintenance history and due-service overview | FR-08, FR-11; UJ-03 | ☐ |
| Active slots and manual booking with server validation | FR-12–14; UJ-04; NFR-S02 | ☐ |
| Owner appointment list/detail | FR-15 (viewing portion only) | ☐ |
| Administrator technician assignment | FR-18 | ☐ |
| Technician assigned appointment and completion/parts workflow | FR-10, FR-16–17, FR-20; UJ-07 | ☐ |
| AgentActionLog read-only inspection, if authorized and records exist | FR-31, FR-35; SRS §6.3 and §8.6 | ☐ |
| Responsive presentation and reproducible documentation | NFR-U01; SRS §9.5–9.6; Appendix A/B | ☐ |

Owner cancellation is not demonstrated here: FR-15 marks it Should, and this runbook does not claim eligibility rules or cancellation behavior that are not part of this demonstrated flow. AI/chat/tool requirements FR-21–34 are not claimed as demonstrated by this runbook. Add an AI segment only after its implementation is approved, integrated, and independently verified; do not infer readiness from a chat screen or an empty AgentActionLog table.

## Screenshot checklist

Capture only local demo data, with no visible credentials or password entry:

- ☐ Owner profile showing role-relevant entry points.
- ☐ Owner vehicle list and an owned vehicle detail page.
- ☐ Maintenance history and due-service overview.
- ☐ Manual booking form showing eligible service/slot choices, with any personal browser data hidden.
- ☐ Saved appointment confirmation and Owner appointment detail.
- ☐ Administrator's unassigned appointment list and assignment form/result.
- ☐ Technician assigned appointment and completion result.
- ☐ Owner vehicle history after completion.
- ☐ AgentActionLog Admin list only if the account is authorized; an empty list is valid when no approved workflow has created records.
- ☐ At least one narrow mobile viewport showing navigation and content without horizontal page overflow.
- ☐ README/runbook and the documentation links used in the closing explanation.

## AgentActionLog inspection instructions and limitation

1. Sign in to Django Admin with an account that is both `is_staff=True` and domain role `ADMINISTRATOR`, and that has the `view_agentactionlog` permission.
2. Visit `/admin/ai_agent/agentactionlog/` or use the role-authorized profile link when it is available.
3. The Admin is read-only. Inspect only the sanitized data that is actually present; do not attempt to add, edit, or delete entries.
4. The page may contain zero rows. Current demo seed data does not create AgentActionLog records, and records appear only when an approved workflow writes them. An empty list is not evidence that an AI action occurred or failed.

## Troubleshooting boundaries

- If a slot is no longer available, return to the booking page and select another displayed eligible slot; do not alter the database during the demo.
- If a role cannot open a page, explain the role boundary. Do not bypass it by changing permissions during the presentation.
- If PostgreSQL or configuration is unavailable, stop the live workflow and show the documentation/checklist instead of switching to SQLite or claiming a successful run.
- Supporting architecture, ERD, and journey documents may contain historical design details. The DOCX SRS and current code determine what is authoritative and implemented.
