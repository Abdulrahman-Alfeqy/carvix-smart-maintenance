# Plan 020: Final Security, Integration, Documentation, Demo, and Submission Audit

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/final-audit-delivery
- Created: 2026-09-28
- Last updated: 2026-09-28

## Objective

Complete the final CARVIX MVP audit against the authoritative SRS: inspect repository truth and security boundaries, verify manual and mocked AI workflows, make only evidence-backed MVP or delivery corrections, validate documentation/demo/traceability, run all prescribed PostgreSQL gates, and conduct a fresh final review. Leave changes uncommitted and stop for human review before any Git delivery action.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`, Version 1.0.

- FR-01–04, UJ-01, NFR-S01–02: registration, login/logout, safe profile fields, role assignment, authenticated access, and CSRF.
- FR-05–08, FR-11, UJ-02–03, NFR-S03, NFR-D01: Owner vehicle CRUD boundary, history, due-service calculations, ownership, and nonnegative mileage.
- FR-09–20, UJ-04, UJ-07, NFR-S04, NFR-R01, NFR-D02–04: service/slot/appointment workflows, capacity and duplicate protection, assignment isolation, valid technician transitions, completion, and inventory consistency.
- FR-21–34, UJ-05–09, SRS §§5 and 8, NFR-S05–07, NFR-R02–03: authenticated AI, least context, exactly the three approved Tools, request.user identity, validation, permissions, explicit confirmation, atomic booking, audited execution, structured outcomes, backend-truth responses, and safe Provider failure.
- FR-35 and SRS §6.3: authorized read-only AgentActionLog inspection.
- NFR-P01–02, NFR-U01–03, NFR-M01–02 and SRS §9.5–9.6 / Appendix A–B: responsive UI, suitable query patterns, visible Chat states, maintainable application boundaries, reproducible setup/demo, and submission evidence.

Priority distinctions: FR-15 and FR-20 are Should requirements. Owner cancellation remains deferred because the SRS does not define the cancellable statuses or behavior precisely enough to add it safely. Parts-used recording is implemented through Technician completion. No optional scope is inferred from supporting documents.

## Current-State Analysis

- Baseline HEAD is `8c2b2a38552e3818f0967189b71fc35f2e300f2b` (`8c2b2a3`, merge of PR #25 / Plan 019). Current branch is `feature/final-audit-delivery`; local `main` points to the same commit and contains it. Initial working tree is clean; `.env` is ignored and untracked.
- `requirements.txt` pins `google-genai==2.25.0`. Production registry and schema maps contain exactly `check_required_maintenance`, `list_available_service_slots`, and `book_maintenance_appointment`.
- `config/settings.py` configures PostgreSQL as the only database, environment-backed credentials, Django CSRF middleware, and the optional Gemini key/model/timeout settings. Initial key-presence checks found no nonblank `GEMINI_API_KEY` in process environment or `.env`; values were not printed. Live smoke test is therefore expected to be NOT RUN.
- The SRS was read in full. `docs/architecture.md`, `docs/erd.md`, and `docs/user-journeys.md` contain historical/speculative elements inconsistent with the SRS and accepted Plans 013–019 (including old role/tool/loop/session/confirmation designs). `docs/README.md` correctly establishes the DOCX as authoritative. Do not redesign architecture or revive removed drafts.
- Plans 013–019 and current routes, forms, views, services, selectors, Tools, Provider, context, prompts, models, Admin registration, seed command, templates, Chat JavaScript, and related tests were inspected. Existing automated coverage is extensive; add a focused test only if the audit identifies a concrete uncovered risk.
- Manual journeys are implemented across `apps.authentication`, `apps.vehicles`, `apps.maintenance`, `apps.appointments`, and `apps.inventory`. Plan 018 covers the complete Fake Provider flow. Plan 019's prior report records PostgreSQL validation but those commands must be rerun for this final audit.
- **MEDIUM integration finding:** `build_safe_context()` does not expose configured ServiceType identifiers/names to any role. However, the slot Tool and booking Tool both require `service_type_id`, the prompt forbids invented identifiers, and the live Provider has no independent access to the database. The integration tests inject known IDs directly from fixtures, so they do not expose this live-workflow gap. This prevents a real Provider from reliably mapping a user's requested service to an approved Tool argument.
- Current docs cover setup and manual demo, but README does not enumerate all approved Tools or clearly state persistent Chat history and other deferred scope. The demo runbook explicitly says AI/chat/tool requirements are not demonstrated and should be added only after integration; Plan 018 and 019 now implement that integration. A concise SRS traceability artifact does not exist. These delivery documentation gaps will be checked and corrected narrowly.

## Endpoint Inventory

| Route family | Endpoint / operation | Access and method |
| --- | --- | --- |
| Django Admin | `/admin/` and registered model administration | Django staff authentication and per-model permissions; domain Administrator status alone does not grant Django staff access. AgentActionLog additionally requires domain ADMINISTRATOR and remains read-only. |
| Authentication | `/accounts/register/` | Public GET/POST; authenticated users are redirected. Registration form fixes role to OWNER and disallows staff/superuser assignment. |
| Authentication | `/accounts/login/` | Public GET/POST; Django authentication/session behavior. |
| Authentication | `/accounts/logout/` | Authenticated, POST-only (OPTIONS also allowed); CSRF middleware applies. |
| Profile | `/accounts/profile/` | Authenticated GET. |
| Profile edit | `/accounts/profile/edit/` | Authenticated GET/POST; form exposes email/name fields only and object is request.user. |
| Vehicles | `/vehicles/`, `/vehicles/new/`, `/vehicles/<pk>/`, `/vehicles/<pk>/edit/` | Owner-only; list/detail/update querysets are owner-scoped, create assigns request.user; form allowlists mutable fields. Create/update mutations use POST and CSRF. |
| Owner appointments | `/appointments/`, `/appointments/<pk>/` | Owner-only GET; querysets scope through `vehicle__owner=request.user`. |
| Manual booking | `/appointments/vehicles/<vehicle_pk>/book/` | Owner-only GET/POST; owned vehicle and server-built service/available-slot form querysets; service rechecks booking inside transaction. |
| Administrator assignment | `/appointments/administrator/assignments/`, `/appointments/administrator/assignments/<appointment_pk>/` | Domain Administrator; list/form GET, assignment POST with confirmation; domain service independently rechecks actor and locks records. |
| Technician work | `/appointments/technician/appointments/`, `/appointments/technician/appointments/<pk>/` | Technician with TechnicianProfile; GET, querysets assignment-scoped. |
| Technician start | `/appointments/technician/appointments/<pk>/start/` | Technician with TechnicianProfile; POST-only; assignment and status rechecked in service transaction. |
| Technician completion | `/appointments/technician/appointments/<pk>/complete/` | Technician with TechnicianProfile; GET form / POST mutation; appointment assignment/status, submitted parts and stock rechecked by backend service. |
| AI Chat page | `/ai/chat/` | Authenticated GET for valid domain roles. |
| AI Chat JSON | `/ai/chat/message/` | Authenticated JSON POST only; CSRF-protected; rejects client identity/context/tool fields and malformed/oversized input. Anonymous response is structured 401. |

Static assets have no custom business endpoint. No owner cancellation endpoint exists.

## Authorization Matrix

| Capability | OWNER | TECHNICIAN | ADMINISTRATOR |
| --- | --- | --- | --- |
| Register | Public registration creates OWNER only | No self-selection | No self-selection |
| Profile | Own profile only | Own profile only | Own profile only |
| Vehicles | Own list/create/detail/update | Denied | No custom domain CRUD claimed; Django Admin permissions govern staff operations |
| Maintenance history / due service | Own vehicles | No Owner maintenance Tool | Django Admin can inspect records only when separately authorized |
| Manual appointments | Own list/detail/book | Denied | Denied by Owner views |
| Technician assignments | Denied | Denied | Assign unassigned appointment to a valid available Technician |
| Technician queue/start/complete | Denied | Assigned records only; start and complete through POST | Denied by Technician views |
| Slot read Tool | Yes | Yes | Yes |
| Maintenance Tool | Own vehicle only | Denied | Denied |
| Booking Tool | Own vehicle, explicit confirmation | Denied | Denied |
| Chat page/message | Valid authenticated domain role | Valid authenticated domain role | Valid authenticated domain role |
| AgentActionLog | No | No | View only when also Django staff with the view permission |

Every domain decision is based on `request.user` and domain role/ownership/assignment checks; `is_staff` and `is_superuser` are separate Django Admin controls.

## Workflow Matrices

### Manual workflow

| Stage | Actor | Existing authority / expected evidence |
| --- | --- | --- |
| Register/sign in | Visitor / Owner | `RegistrationForm`, Django `LoginView`, hashed password, session; role cannot be selected. |
| Vehicle management | Owner | `VehicleForm`; owner assigned from request.user; detail/update object querysets scoped by owner. |
| Maintenance view | Owner | Owner-scoped Vehicle detail calls `get_vehicle_maintenance_overview`; shows history and calculated due services. |
| Slot discovery and booking | Owner | `get_available_service_slots`; validated form; `book_appointment` owns atomic slot lock, active-capacity recheck and duplicate prevention; manual `booked_by_agent=False`. |
| Assignment | Administrator | Confirmed form and `assign_technician`; role/TechnicianProfile validation, appointment/profile locks, only technician relation updated. |
| Start/complete | Assigned Technician | POST start; atomic completion checks appointment/status/mileage/parts, creates maintenance data, locks SpareParts deterministically, prevents negative stock and duplicate completion. |
| History/inventory review | Owner / authorized staff | Maintenance history derives from persisted completion; authorized Admin surface follows Django Admin permission model. |

### AI workflow

| Stage | Actor / boundary | Existing authority / expected evidence |
| --- | --- | --- |
| Chat request | Authenticated domain role | CSRF-protected POST; strict JSON validation; context is built server-side. |
| Maintenance Tool | Owner | Role/owned Vehicle check, existing due-service function, read-only result. |
| Slot Tool | Owner, Technician, Administrator | Role and service validation, existing global active/future/capacity selector. `preferred_date` is validated but does not filter; no service-to-slot compatibility relation exists. |
| Booking Tool | Owner | Exact `confirmation is True`; server actor injection; existing booking service; `booked_by_agent=True` set server-side. |
| Registry / audit | Django | Explicit allowlist only; one sanitized AgentActionLog per registered execution attempt; success booking and SUCCESS log atomic. |
| Provider | Gemini adapter | No ORM/domain model or callable access; role-filtered declarations and minimal sanitized context; no automatic execution or retries; max three Tool rounds; all execution stays in Django. |
| Final response | Agent | Structured observations and backend results override Provider claims; repeated/second booking and side effects after failure are blocked. |

## Transaction and Secret-Handling Matrices

### Transaction boundaries

| Operation | Transaction / concurrency controls |
| --- | --- |
| Manual booking | `book_appointment` atomic; Slot row lock; future/active/capacity/duplicate recheck; database active slot/vehicle uniqueness constraint. |
| AI booking + audit | Outer dispatcher atomic surrounds existing nested booking service and SUCCESS audit. A success-audit failure rolls back appointment. Failure handler effects roll back before one failure-audit attempt. |
| Tool read + audit | Tool dispatch/audit transaction; maintenance/slot handlers do not mutate business data. |
| Technician assignment | Atomic; locks Appointment and valid TechnicianProfile; does not replace an existing assignment. |
| Maintenance completion | Atomic; locks assigned Appointment and SpareParts in stable primary-key order; writes MaintenanceRecord/MaintenancePart, decrements stock, updates Appointment; any failure rolls back all writes. |
| Provider call | Outside database transactions and row locks. SDK automatic retries disabled. |

### Secret checklist

- [x] `.env` ignored and untracked; secrets absent from tracked history/files and examples contain placeholders only.
- [x] No Gemini key, database password, authorization header, cookie, or credential URL is printed or stored in logs, prompts, tool schemas/arguments, AgentActionLog, templates, or Chat JSON.
- [x] Settings load credentials only from environment; no secret-bearing value reaches the browser or Provider context.
- [x] Sanitization recursively redacts credential-like keys; provider and tool exceptions are contained without raw exception text or traceback.
- [x] Test data contains placeholders/fake nonfunctional values only; no real-looking credential fixture.

## Documentation, Demo, and Traceability Checklists

- [x] README setup instructions match Python 3.12+, PostgreSQL-only configuration, `.env.example`, migrations, dependency installation, seed, server, and test commands.
- [x] README accurately describes optional Gemini setup, `gemini-flash-latest`, timeout, no-key behavior, exact three Tool names, manual workflows, and deferred scope.
- [x] `docs/demo-runbook.md` presents seeded manual journeys truthfully; AI demo boundaries and empty/nonempty log interpretation match current integrated code.
- [x] `docs/demo-seed-data.md` and seed command agree on accounts, data, repeatability, password safety, and limitations.
- [x] Architecture and ERD references are identified as supporting/historical where they disagree; no redesign or stale requirement adoption.
- [x] Added `docs/final-traceability.md` as a concise requirement-to-code-and-validation map; it points to the DOCX SRS and does not duplicate it.
- [x] Every Must FR and relevant NFR is mapped to implemented workflow/evidence or accurately marked as a finding/deferred requirement. FR-15 cancellation is explicitly identified as Should and deferred; no cancellation claim is made.

## Tool Matrix

| Exact registered name | Allowed role | Arguments / side effect | Backend authority / audit |
| --- | --- | --- | --- |
| `check_required_maintenance` | OWNER | `vehicle_id`; read-only | Owner-scoped Vehicle query and existing due-service service; central sanitized execution audit. |
| `list_available_service_slots` | OWNER, TECHNICIAN, ADMINISTRATOR | `service_type_id`, optional validated `preferred_date`; read-only | Existing active/future/remaining-capacity selector; global slots and no date filtering per accepted Plan 017; central audit. |
| `book_maintenance_appointment` | OWNER | `vehicle_id`, `service_type_id`, `slot_id`, exact boolean `confirmation`; creates appointment only when true | Existing booking service with server-owned `booked_by_agent=True`; central atomic success audit. |

No aliases, identity arguments, extra Tools, Provider callables, ORM access, SQL, or execution by Gemini.

## Risks and Problems

- Legacy supporting diagrams contain unsupported features/values; the DOCX SRS and accepted plans control. Avoid turning those into corrections.
- A demo booking consumes a seeded slot, and completion consumes stock; the runbook must specify local-only rehearsal and how to select a remaining eligible slot.
- Live Gemini credentials are absent at discovery. Mocked tests remain the primary verification and live smoke is not a completion blocker.
- A documentation traceability artifact can become a duplicate requirements source; keep it concise and link to the DOCX.
- Any previously unknown model/migration discrepancy would exceed this plan; stop and ask the human before proposing schema changes.
- Existing plans 013–019 include prior manually reported test results. The final report will distinguish this run's executed results from prior plan claims.

## Evidence-Backed Finding and Approved Correction

### MEDIUM — AI slot/booking journey cannot reliably select a ServiceType

- **Evidence:** `apps/ai_agent/context.py::build_safe_context()` currently gives the Provider role/vehicle/appointment summaries but no ServiceType catalog. `apps/ai_agent/tool_schemas.py` requires `service_type_id` for both `list_available_service_slots` and `book_maintenance_appointment`. `CARVIX_SYSTEM_PROMPT` prohibits inventing identifiers. Live Gemini receives neither ORM access nor another source for the service ID. Fake Provider integration tests provide IDs directly from their fixture and therefore do not test this mapping.
- **Impact:** A live user can ask to find/book a named service, but the Provider cannot correctly translate that name to an existing ID without guessing. The SRS AI-assisted slot and booking journey is consequently not reliably usable end to end.
- **Why documentation/test-only changes are insufficient:** Documentation cannot deliver the required configured service identifiers to the live Provider. A test-only correction would preserve a broken production context.
- **Alternatives considered:** (A) include only configured ServiceType IDs and names in server-built context for roles allowed to use the slot Tool; this is minimal, safe catalog data and enables exact selection. (B) let the model guess IDs or query through a new Tool; guessing violates the prompt/security contract and a new Tool changes the approved three-tool interface. Choose A.
- **Approved correction:** Add a JSON-native `service_types` list of `{id, name}` from configured ServiceTypes to the role-safe context for the three valid domain roles. Do not include prices, descriptions, owner-specific data, or new identity fields. Add focused coverage proving the configured catalog is available for slot-capable roles and excluded data remains absent. Update only if the independent audit finds a stronger reason to narrow this data further.
- **Files:** `apps/ai_agent/context.py`, existing focused context/integration tests (expected `apps/ai_agent/tests.py` or `apps/ai_agent/test_tool_integration.py`). No Model, Migration, endpoint, schema, Tool name, permission, or Provider contract change.

### Delivery-critical LOW — Chat page still describes the pre-integration foundation

- **Evidence:** `templates/ai_agent/chat.html` tells users that “No appointment or other action can be completed from this foundation,” which is false after Plan 018/019; the booking Tool is available after explicit confirmation.
- **Impact:** The primary Chat entry point contradicts the implemented product and can mislead a demo or Owner about available actions.
- **Why documentation elsewhere is insufficient:** This is user-facing page content and must be corrected in the template users see.
- **Approved correction:** Replace the stale sentence with a concise statement of maintenance guidance, slot discovery, and booking only after explicit confirmation. Do not imply the AI performs any action without the registered backend Tool.
- **Files:** `templates/ai_agent/chat.html`.

### Delivery-critical LOW — setup/demo documentation points at an undefined root route

- **Evidence:** `README.md` and `docs/demo-runbook.md` instruct users to open `http://127.0.0.1:8000/`; `config/urls.py` has no root route. The implemented public entry is `/accounts/login/`.
- **Impact:** A person following the setup guide or demo runbook reaches a 404 before sign-in.
- **Approved correction:** Change both instructions to the existing login URL and note that successful sign-in redirects to the profile page.
- **Files:** `README.md`, `docs/demo-runbook.md`; no routing change is justified because the project has an existing entry route.

## Alternatives Considered

### Option A — Evidence-based audit with narrow documentation corrections (Recommended)

Run the requested security/integration gates, make only proven delivery corrections, and add a compact traceability map. This closes final submission gaps while preserving approved behavior. Its cost is a thorough sequential PostgreSQL validation pass.

### Option B — Documentation-only sign-off

Rely on earlier plan reports and leave docs as-is. This is faster but would not independently satisfy the final security, integration, PostgreSQL, or submission audit requested for Plan 020.

## Recommended Approach

Use Option A. The branch is the requested clean baseline and the authoritative SRS and completed plans settle the product behavior. Current discovery identifies one proven Provider-context defect and documentation omissions. The narrow context correction above is approved; other source changes remain limited to proven defects. Any Model/Migration proposal remains blocked pending human decision.

## Implementation Steps

1. Complete static security and endpoint audit; inspect test coverage and repository truth without printing credentials.
2. Implement the approved ServiceType context correction and focused regression coverage; make no speculative product changes.
3. Update README and demo runbook only where inaccurate/incomplete; create concise `docs/final-traceability.md`.
4. Check PostgreSQL, then run every required validation command in the exact task-specified order; stop at the first genuine failure.
5. Inspect all changed files, Model/Migration state, secret scan, full diff, and final branch/tree state; conduct a fresh independent review for BLOCKER/HIGH/MEDIUM and delivery-critical LOW findings.
6. Finalize this plan as IMPLEMENTED only if every gate passes; leave the worktree unstaged and stop for human review.

## Security Test Plan

- Authentication and role gates: anonymous private HTML/JSON endpoints; login/registration behavior; POST-only logout and mutations; safe `next`; invalid role/profile; domain role independent of Django staff/superuser.
- Owner/Technician isolation: URL IDOR across Vehicles, history, appointments and assignment; Technician assigned querysets; cross-owner maintenance/booking Tools; Technician without profile; forged relation IDs/fields.
- CSRF/methods: test all mutating views with POST and enforced CSRF; confirm GET has no write side effect; Chat JSON POST is protected; GET Tool trigger is impossible.
- Mass assignment: role, owner/user, technician, status, `booked_by_agent`, Slot capacity/active state, Appointment relation, and arbitrary Tool fields rejected or ignored with no unauthorized effect.
- Admin: assignment role and profile validation; AgentActionLog view permission/domain role intersection/read-only behavior; no role-to-staff escalation.
- Provider/Agent: no ORM/domain models in adapter, exact role-filtered registry/schema, server actor injection, provider calls outside transactions, three-round cap, malformed/mixed replies rejected, duplicate and repeated booking prevented, safe false-success fallback.
- Audit/transactions: one audit per registered dispatch; safe arguments/results; success booking and audit atomic; failure rollback; safe exception handling; assignment/completion/stock atomic and deterministic locks.
- Secrets/errors: `.env` ignored/untracked, scan tracked/changed content without printing matches, test placeholder fixtures, safe logs/responses/provider failures, no key in context or schema.

## Regression Test Plan

Run the task's required order exactly with `.venv/bin/python` and PostgreSQL only: Django check; migration check; Plan 020 focused test if created; live Provider tests; Tool integration; all AI Agent tests; Authentication tests; Appointments/Vehicles/Maintenance/Inventory tests; Demo Seed Data tests; complete suite; whitespace; Model/Migration inspection; secret scan; documentation-command verification; final changed-file scope. No live booking through Gemini. Live smoke is at most two non-mutating Provider calls and only when a key is present.

## Expected Files

- `.agents/plans/020-final-audit-delivery.md` — this plan and final evidence/report.
- `README.md` — only verified setup/tool/deferred-scope corrections.
- `docs/demo-runbook.md` — only truthful final demo updates.
- `docs/final-traceability.md` — concise SRS traceability artifact if confirmed useful.
- `apps/ai_agent/context.py` and an existing AI context/integration test module — the approved ServiceType-context correction and regression coverage.
- `templates/ai_agent/chat.html` — correct stale pre-integration user guidance.
- A focused audit test module only if static/test inspection exposes a real security risk lacking regression coverage.
- Production files only for a demonstrated blocker/high/medium defect, after documenting severity, evidence, and why a test/docs-only correction is insufficient.

No Model, Migration, dependency, or environment-variable change is planned. Do not edit old supporting diagrams or removed drafts.

## Correction Policy

Correct only a genuine BLOCKER/HIGH/MEDIUM or delivery-critical LOW documentation issue. For every production correction: record concrete evidence and severity in this plan first; explain why docs/tests alone cannot resolve it; implement the smallest safe change; add focused regression coverage; run the narrow test, affected app tests, and full suite. Optional scope is not a defect. Stop for a human decision if requirements conflict or any Model/Migration change appears necessary.

## Migration, Environment, and Rollback Policy

`MIGRATIONS_EXPECTED: NO`. No schema change, dependency change, or new environment variable is planned. Any Model/Migration proposal is a blocker for this plan. Roll back only the specific approved-scope corrections and tests; retain original application behavior and do not alter database contents. Test DB setup/teardown is handled by Django; do not seed a shared database.

## Definition of Done

- SRS Must requirements are mapped to current code and evidence; actual issues are corrected or reported without scope invention.
- Authentication, ownership, role, assignment, CSRF, mass assignment, secret, Provider, audit, transaction, and false-success checks have evidence from code and tests.
- Manual and Fake Provider AI journeys are verified; Gemini is never used to book during this audit.
- README, runbook, seed docs, and traceability artifact are accurate and reproducible.
- All required PostgreSQL gates pass in order; any failure stops the run and is reported exactly.
- No Model/Migration change, secret, unrelated file, staged file, commit, push, PR, tag, or merge is made.
- Final independent review has no unresolved BLOCKER/HIGH/MEDIUM or delivery-critical LOW finding.
- Final report records exact test totals and current Git state; plan status becomes IMPLEMENTED only after every gate and review is complete.

## Open Questions

None blocking. The explicit user authorization to execute Plan 020 sets Decision to APPROVED. No architecture, role, model, or scope decision is needed from the human at this stage.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-28

## Implementation Report

Completed on 2026-09-28 against baseline `8c2b2a38552e3818f0967189b71fc35f2e300f2b` on `feature/final-audit-delivery`.

### Corrections and delivery artifacts

- Corrected the MEDIUM Provider-context defect by adding configured ServiceType `{id, name}` pairs to the server-built context for each valid domain role. Focused context and Fake Provider tests verify IDs come from server context and that descriptions/prices are excluded. No Model, Migration, route, Tool, or Provider contract changed.
- Corrected the stale Chat page guidance and the README/runbook sign-in URL, which pointed to an undefined root route.
- Added the concise SRS-to-code/test map in `docs/final-traceability.md`; README and runbook now describe the exact three Tools, optional Gemini behavior, actual manual and AI boundaries, global slot semantics, and deferred scope accurately.
- Added two regression tests to existing AI test modules. No test module was added solely for this audit.

### Audit and integration results

- Reviewed the full authoritative SRS, approved Plans 013–019, setup and seed documentation, environment example, settings, all application URL routes, security-relevant views/forms/services/selectors, Tool handlers/registry, Agent loop and both Provider adapters, context/prompt, AgentActionLog model/Admin/sanitizer, seed command, demo templates/JavaScript, and related tests.
- Recorded the public/authenticated endpoint inventory, Owner/Technician/Administrator access matrix, manual and AI workflows, Tool contracts, secret handling, and transaction boundaries above. Code and tests show request.user-bound identity, backend role/ownership/assignment enforcement, POST and CSRF protection for writes, validated forms/schemas, explicit AI confirmation, exactly three allowlisted Tools, server-owned booking flags, Provider isolation from ORM/execution, sanitized exactly-once Tool audit behavior, atomic booking/audit and completion/inventory work, bounded Tool loops, duplicate side-effect controls, and backend-truth responses.
- The complete non-live seeded journey passed in one isolated PostgreSQL test-database transaction: login entry, Owner vehicle/history/due view, eligible slot discovery, manual booking, Owner appointment list/detail, Administrator assignment, Technician queue/detail/start/completion, stock decrement, updated Owner history, a read-only registered Tool audit, and authorized read-only AgentActionLog inspection. Django destroyed the isolated test DB afterward; the local demo database was not seeded or modified.
- The Fake Provider path is covered by the full Tool-integration suite, including maintenance/slot/confirmed-booking behavior, audit, rollback, and backend-truth cases. No live Gemini request was sent.
- Five repeated in-process `GET /vehicles/` requests with seeded PostgreSQL test data measured max `0.005s`, median `0.004s` in Django's test client. This does not claim production/network load performance. The browser login layout was checked at 390px and 1440px; the document width matched each viewport. Responsive CSS/templates/JavaScript were inspected; other authenticated pages remain on the manual demo screenshot checklist.
- Gemini key-presence check was negative in both process environment and `.env`; the key value was never printed. `LIVE_SMOKE_TEST: NOT RUN`; `LIVE_GEMINI_CALL_COUNT: 0`.
- The configured local database reports `ai_agent.0001_initial` as unapplied, and local `.env` resolves `DEBUG=False`. These local settings were not changed and the migration was not applied to the user's configured database. The README already instructs developers to run `migrate` and set `DEBUG=True` for local `runserver` static files; under a temporary `DEBUG=True` process override, the stylesheet returned HTTP 200 and the 390px login view was styled with no horizontal overflow. The full test suite and seeded journey used isolated PostgreSQL test databases with migrations applied.

### Required PostgreSQL validation order and exact results

1. `.venv/bin/python manage.py check` — PASS; no system-check issues.
2. `.venv/bin/python manage.py makemigrations --check` — PASS; no changes detected.
3. Plan 020 focused tests — PASS, 2/2: `AiAgentContextTests.test_service_catalog_gives_slot_capable_roles_only_existing_ids_and_names` and `SlotToolLoopTests.test_provider_can_select_the_named_service_from_server_context`.
4. `.venv/bin/python manage.py test apps.ai_agent.test_live_provider -v 1` — PASS, 19/19.
5. `.venv/bin/python manage.py test apps.ai_agent.test_tool_integration -v 1` — PASS, 19/19.
6. `.venv/bin/python manage.py test apps.ai_agent -v 1` — PASS, 111/111.
7. `.venv/bin/python manage.py test apps.authentication -v 1` — PASS, 65/65.
8. `.venv/bin/python manage.py test apps.appointments apps.vehicles apps.maintenance apps.inventory -v 1` — PASS, 164/164.
9. `.venv/bin/python manage.py test apps.maintenance.test_seed_demo_data -v 1` — PASS, 4/4 (included within the domain-app total, not an additional distinct test set).
10. `.venv/bin/python manage.py test -v 1` — PASS, 340/340.
11. `git diff --check` — PASS.
12. Model/Migration inspection — PASS; no model or migration file changed, and `makemigrations --check` found no changes.
13. Secret scan — PASS; `.env` is ignored/untracked; no Gemini key in process environment or `.env`; common Google/AWS key and private-key patterns checked across 160 current non-ignored files and 527 Git objects with no matches. No matched secret values were printed. `.env.example` contains placeholders.
14. Documentation-command verification — PASS; documented migration, server, and seed commands are registered (`manage.py help`); documented application/test targets resolve to repository test modules; system/migration/full-suite and seed tests passed; all local Markdown links in README, demo runbook, and traceability resolve; login/Admin paths were exercised in the isolated journey.
15. Final scope inspection — PASS; expected branch retained, no `.env` tracked, no secrets found, no Model/Migration/dependency/environment changes, no unrelated file, and no staged file.

The one-off seeded journey ran as 1/1 in an in-memory test module against Django's temporary PostgreSQL test database. It was not persisted as a new repository test. Its initial harness assertion expected the login page to return 200 after authenticating; the app correctly redirected authenticated users, so the check was corrected to use an anonymous client and the integrated journey then passed. No product code change was needed for this harness-only correction.

### Independent reviewer verdict

Fresh review of the complete final diff, modified production code and tests, Plan 020, README, runbook, traceability map, `.env.example`/settings, and Provider/Tool execution boundaries found no unresolved BLOCKER, HIGH, MEDIUM, or delivery-critical LOW issue in this task's changes. The ServiceType catalog contains only configured IDs/names needed by the approved slot/booking schemas; it does not add client-controlled identity or disclose prices/descriptions. Documentation claims and tested behavior align. One pre-existing plan-governance note remains outside this change set: Plan 015 is still marked APPROVED with an implementation report pending, although its frontend/docs files are present in the baseline; its historical desktop/mobile review criteria were not re-audited in full and Plan 015 was not modified. Final verdict for Plan 020: APPROVABLE for human review; leave unstaged and await human approval before Git delivery actions.

No deviation from the approved Plan 020 scope. The optional live Gemini smoke test remains NOT RUN because no key is configured. No staging, commit, push, Pull Request, tag, or merge was performed.

## Final Deferred Scope

Owner cancellation (FR-15 Should; eligibility semantics undefined), persistent Chat history, and all scope excluded by `AGENTS.md` remain deferred. Gemini live smoke test may remain NOT RUN when no key is configured. No RAG, embeddings, vector database, multiple agents, voice, maps/GPS, payments, WebSockets, predictive ML, multiple branches, supplier/financial systems, custom generic RBAC, or raw SQL is included.
