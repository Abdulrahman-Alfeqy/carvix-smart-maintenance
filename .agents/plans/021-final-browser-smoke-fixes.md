# Plan 021: Final Browser Smoke Remediation

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: `fix/final-browser-smoke`
- Created: 2026-09-28
- Last updated: 2026-09-28

## Objective

Resolve the verified final browser-smoke findings with minimal changes to the approved CARVIX MVP: serve the existing Chat JavaScript through Django staticfiles, expose Chat in authenticated navigation, provide a safe root entry redirect, keep internal seed metadata out of Maintenance History while preserving deterministic seed updates, and report seeded-password usability accurately. Do not make a live Gemini request or perform Git delivery actions.

## Requirements Covered

Authoritative source: `docs/CARVIX_SRS_Group6.docx`, Version 1.0; current product behavior follows approved Plans 015, 018, 019, and 020, `AGENTS.md`, `README.md`, and `docs/demo-runbook.md`.

- SRS §4 and §8.1: authenticated, domain-limited Chat entry point.
- SRS §9.5–9.6 and Appendix A/B: HTML/CSS/ES6 browser experience, responsive navigation, reproducible local demo, and truthful setup guidance.
- NFR-S01–04 and SRS §8.1: authentication, CSRF-protected browser requests, and backend authorization independent of navigation visibility.
- FR-08, FR-11 and UJ-03: user-facing maintenance history and due-service behavior.
- SRS §9.6 and approved Plan 015: deterministic local demo data and safe credential handling.
- Existing accepted project contract: PostgreSQL-only validation, no Model or Migration changes, no scope expansion, and no staging/commit/push/PR/merge.

## Current-State Analysis

- Repository truth is clean branch `fix/final-browser-smoke` at expected HEAD `3e4f2afb9564ede87cd95f6ddb1b59195941cffc`.
- `config/settings.py` enables `django.contrib.staticfiles` and sets `STATIC_URL`, but leaves `STATICFILES_DIRS` empty and `STATIC_ROOT` unset. `static/js/agent_chat.js` exists only in the project-level `static/` tree. `.venv/bin/python manage.py findstatic js/agent_chat.js --verbosity 2` reports no matching file and searches only installed app static locations.
- `templates/ai_agent/chat.html` already uses Django's static tag for `js/agent_chat.js` and renders the namespaced message endpoint in the form. The existing JavaScript POSTs JSON to that endpoint with same-origin credentials and the form's CSRF token. Existing AI tests cover Chat validation and enforced CSRF, and patch the Provider for requests that invoke it.
- `static/css/carvix.css` and `apps/authentication/static/css/carvix.css` are identical tracked copies. Enabling project static discovery would make `css/carvix.css` resolve from two locations. The README currently explains the old mirror workaround; consolidate discovery on the project static tree and correct that statement.
- `templates/base.html` exposes role-specific links only after authentication; it has no Assistant/Chat link. `apps/ai_agent.views.chat_page` uses `login_required`; the JSON view authenticates and validates the three existing domain roles. A UI link does not change backend permissions.
- `config/urls.py` has no root route. The existing namespaced Login route redirects authenticated users to the existing Profile convention.
- `seed_demo_data` wrote reserved `CARVIX_DEMO_SEED:v1:record:*` strings into `MaintenanceRecord.notes` and located records by those notes. The Owner vehicle detail template displays nonempty Notes verbatim. A tagged Appointment is not sufficient by itself to authorize changing an attached record: its vehicle, service, technician, Appointment, date, and mileage must match the exact deterministic seed definition. New and blank-note exact Demo records receive the descriptive Note; only the exact per-key legacy marker is migrated; arbitrary nonblank Notes remain unchanged.
- `_summary()` always says passwords are unusable unless the environment variable was provided, which remains misleading when it was provided. The password itself is not currently printed.
- `pg_isready` reports PostgreSQL accepting connections. No Model or Migration change is indicated by the inspected files.

## Findings and Approved Corrections

### BLOCKER — Project Chat JavaScript is not discoverable

- **Evidence:** the template references `/static/js/agent_chat.js`; the file exists under project `static/js/`; `STATICFILES_DIRS` is empty; baseline `findstatic` finds no match.
- **Root cause:** Django's FileSystemFinder has no project static directory configured.
- **Correction:** set `STATICFILES_DIRS` to the project `static/` directory and configure `STATIC_ROOT` under the already ignored `staticfiles/` output directory so `collectstatic` remains runnable. Remove the duplicate app-level CSS copy so the now-discoverable CSS path has one source. Preserve the existing template asset name and JavaScript endpoint/CSRF contract. Document that `DEBUG=True` runserver serving is local development behavior and production `DEBUG=False` requires a static server/CDN or equivalent deployment configuration.
- **Expected files:** `config/settings.py`, remove `apps/authentication/static/css/carvix.css`, update `README.md`, add static/settings regression coverage and Chat contract coverage.

### MEDIUM — Authenticated navigation omits Chat

- **Evidence:** authenticated `templates/base.html` has profile/edit and role workflow links, but no Assistant/Chat link; the established Chat page is a named authenticated route available to each valid domain role.
- **Root cause:** the shared layout does not include the existing Chat route.
- **Correction:** add a clearly labeled Assistant link for authenticated users using `{% url 'ai_agent:chat' %}`. Keep it within the existing authentication condition and leave all backend checks unchanged. The existing flex-wrap navigation remains responsive.
- **Expected files:** `templates/base.html`, existing AI chat/navigation tests.

### MEDIUM — Root URL returns 404

- **Evidence:** `config/urls.py` has no `/` pattern; the accepted sign-in route is `authentication:login`; authenticated visits to Login already redirect to Profile.
- **Root cause:** no root URL pattern delegates users to the existing authentication entry flow.
- **Correction:** add a permanent-false root redirect to the namespaced Login route, ignoring external `next` input. Anonymous visitors reach Login; authenticated visitors follow the existing Login-to-Profile redirect convention. Add no dashboard or landing page.
- **Expected files:** `config/urls.py`, focused root route tests.

### MEDIUM — Internal seed marker appears as Maintenance History Notes

- **Evidence:** the seed command assigns `CARVIX_DEMO_SEED:v1:record:*` to `MaintenanceRecord.notes`; `templates/vehicles/vehicle_detail.html` displays Notes; tests confirm note visibility. The marker is also the current record lookup key, so removing it alone would break repeatability.
- **Root cause:** internal idempotency metadata is stored in a user-facing field and used as the only identity for finding the seeded record.
- **Correction:** locate each candidate through its reserved historical Appointment and verify the full record identity against the exact seed definition before changing it. Assign the descriptive Note to new records, fill blank Notes on verified deterministic records, replace only the exact legacy marker for that key, and leave existing descriptive or arbitrary nonblank Notes unchanged. Reject a mismatched record even when attached to the tagged Appointment. Update count assertions to identify seeded records through the tagged Appointment relation; cover blank Notes, repeated runs, marker-like custom text, and mismatched linked records.
- **Expected files:** `apps/maintenance/management/commands/seed_demo_data.py`, `apps/maintenance/test_seed_demo_data.py`, `docs/demo-seed-data.md`, and only if needed a narrowly scoped existing vehicle-history test.

### LOW — Seed summary misstates password usability

- **Evidence:** `_summary()` always emits that seeded passwords are unusable unless `CARVIX_DEMO_PASSWORD` was provided, regardless of whether it was.
- **Root cause:** summary text is not conditional on the command's already-read password value.
- **Correction:** select an accurate summary sentence from the boolean password-provided state. Never include the password or any environment value in output. Add absent/present-output tests with a non-production fixture secret.
- **Expected files:** `apps/maintenance/management/commands/seed_demo_data.py`, `apps/maintenance/test_seed_demo_data.py`.

## Risks and Problems

- Project static discovery activates the existing root CSS copy; retaining the app mirror would make the stylesheet path ambiguous. Remove only that duplicate and verify `findstatic` returns a single CSS source.
- `STATIC_ROOT` is a production collection destination, not a development file server. Documentation and browser verification must not imply Django serves static assets when `DEBUG=False`.
- Navigation is presentation only. Chat remains protected by its existing backend authentication/role checks; tests will cover anonymous access and each domain role's current workflow navigation.
- Seed records may already contain markers or blank Notes in a local database. A reserved Appointment plus a full field-by-field match to the exact seed definition establishes deterministic identity. Only then may the command fill blank Notes or replace the exact legacy marker. Preserve all arbitrary nonblank Notes and existing seeded row counts; reject mismatched linked records.
- Password output tests must assert the secret fixture is absent without printing it in test logs or reports.
- Run tests only against the configured PostgreSQL test database. Stop at the first genuine test/validation failure and classify before any further correction.

## Alternatives Considered

### Option A — Configure project static discovery and repair seed generation (Recommended)

Register the existing project static directory and a collection destination; remove the duplicate CSS mirror to avoid name ambiguity. Reuse the seed Appointment identity to store real Notes. This fixes root causes in the smallest existing boundaries, preserves collectstatic, and avoids any schema change.

### Option B — Copy the JavaScript into an installed app and filter marker strings in the template

Copying the JS would make the URL discoverable without settings changes, but would split static ownership and risk future duplicate assets. Template filtering would hide an implementation marker but keep it in the database and leave seed idempotency tied to presentation data. This is less robust and creates additional ambiguity.

### Option C — Add a dashboard or authenticated root view and a new seed metadata field

This would create new behavior and schema/UI scope. It is unnecessary because the existing Login/Profile flow, seed Appointment relation, and existing Notes field are sufficient.

## Recommended Approach

Use Option A. It follows the SRS and accepted plan boundaries, uses existing namespaced routes and seed identities, preserves backend authorization and user-authored notes, and requires no model/schema migration or live Provider request.

## Implementation Steps

1. Add focused static, Chat navigation/contract, and root-route regression tests; adjust seed regression coverage for tagged-Appointment identity, rendered Notes, idempotency, and summary output.
2. Configure project `STATICFILES_DIRS` and ignored `STATIC_ROOT`, remove the app CSS duplicate, add the authenticated namespaced Chat link, and add the safe root redirect.
3. Update seed lookup/notes and conditional summary output; update README's static discovery note and `docs/demo-seed-data.md`'s seed-marker description.
4. Run the exact PostgreSQL validation sequence below, then static collection/discovery and optional local browser smoke. Stop at the first genuine failure and classify it.
5. Inspect model/migration status, secret exposure, full diff, browser/security behavior, and final unstaged Git state; conduct the independent review.
6. Complete this report and set Status to `IMPLEMENTED` only after all required gates and review pass. Do not stage or perform any Git delivery action.

## Test Plan

- Static configuration: project `static/` is in `STATICFILES_DIRS`; `STATIC_ROOT` is a distinct collection destination; `findstatic js/agent_chat.js --verbosity 2` resolves exactly one project file; `findstatic css/carvix.css` resolves exactly one project file.
- Chat contract: every valid authenticated domain role sees the script, namespaced form endpoint, CSRF source, and authenticated Assistant link; JavaScript uses same-origin JSON `fetch` with `X-CSRFToken`; no duplicate asset; anonymous Chat page access redirects to Login; existing validation/CSRF tests pass with no live Provider network call.
- Navigation: current Owner, Administrator, and Technician links remain in the base layout and the Chat link uses `ai_agent:chat`; anonymous navigation has no Chat link.
- Root: anonymous `GET /` redirects to the exact Login URL, including when an external `next` parameter is supplied; authenticated requests follow the existing Login-to-Profile behavior; GET causes no data creation.
- Seed Notes policy: new exact Demo records receive descriptive Notes; exact legacy markers migrate; blank Notes on exact deterministic Demo records receive the descriptive Note; existing descriptive Notes remain unchanged; arbitrary nonblank Notes including marker-like text are preserved exactly across repeated runs. Appointment tagging alone never authorizes Notes or record-field overwrites; mismatched linked records fail safely. Seed counts remain stable and generated Demo records contain no internal markers.
- Seed summary: absent variable reports unusable passwords; provided variable reports usable seeded demo credentials; output contains no secret value.
- Run the relevant focused Plan 021 tests, Seed Data tests, Authentication tests, AI Agent tests, domain tests, and complete suite in the prescribed order. Do not weaken existing assertions.

## PostgreSQL Validation Order

Use `.venv/bin/python` and PostgreSQL only. Run sequentially and stop at the first genuine failure:

1. `pg_isready`
2. `.venv/bin/python manage.py check`
3. `.venv/bin/python manage.py makemigrations --check`
4. `.venv/bin/python manage.py test apps.ai_agent.test_browser_smoke apps.maintenance.test_seed_demo_data -v 2`
5. `.venv/bin/python manage.py findstatic js/agent_chat.js --verbosity 2`
6. `.venv/bin/python manage.py test apps.maintenance.test_seed_demo_data -v 2`
7. `.venv/bin/python manage.py test apps.authentication -v 2`
8. `.venv/bin/python manage.py test apps.ai_agent -v 2`
9. `.venv/bin/python manage.py test apps.appointments apps.vehicles apps.maintenance apps.inventory -v 2`
10. `.venv/bin/python manage.py test -v 2`
11. `git diff --check`
12. Model and Migration inspection
13. Secret scan
14. Complete diff review

After each production correction, rerun its focused test, relevant suites, and the complete suite. The focused Plan 021 command above completed successfully after correcting two test-harness mistakes found on its first run: an unsupported finder-helper keyword and a case-sensitive output assertion.

## Optional Browser Verification

The temporary local server started on `127.0.0.1:8765` with a process-local `DEBUG=True` override and was stopped cleanly. No-follow HTTP checks returned `/` → 302 `/accounts/login/`, `/static/js/agent_chat.js` → HTTP 200 `text/javascript` (2,677 bytes), and anonymous `/ai/chat/` → 302 `/accounts/login/`. The script response contains the endpoint fetch, same-origin credentials, and CSRF header. The in-app browser opened the root and displayed the Login page; direct navigation to the JavaScript file was blocked by the browser, and no authenticated browser session was used. The authenticated Chat template/script reference and fetch contract passed PostgreSQL regression tests, but a real authenticated browser load was not observed. Manual final browser steps: start the local server with `DEBUG=True`, sign in with an existing local demo Owner account, open **Assistant**, confirm `/static/js/agent_chat.js` returns HTTP 200 in the browser Network panel, and stop the server. Do not submit a Chat message or make a live Gemini request.

## Migration and Environment Impact

- `MIGRATIONS_EXPECTED: NO`; no Model or Migration change is permitted.
- No new dependency, secret, or environment variable. `STATICFILES_DIRS` points to the existing project asset tree; `STATIC_ROOT` points to the already ignored `staticfiles/` output directory used by `collectstatic`.
- Local `DEBUG=True` static serving is for development only. A `DEBUG=False` deployment must configure a production static-file server or equivalent and must not be represented as Django development static serving.
- Before updating data, a read-only check confirmed the configured PostgreSQL host is local, the expected seed counts matched exactly, and 3 seeded MaintenanceRecords still contained legacy markers. Then `.venv/bin/python manage.py seed_demo_data` ran once against that verified local demo dataset. It completed atomically, reported usable seeded credentials without showing the password, preserved expected counts, corrected all 3 Notes, and left 0 record markers. No production migration or Model change occurred.
- Rollback is limited to reverting the plan's route, settings, navigation, seed, test, documentation, and duplicate-file changes. The one-time local seed-data correction affects only records identified by the existing reserved demo identities/markers; reverting source code will not restore the old Notes values.

## Open Questions

None blocking, provided repository truth remains as inspected.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-28

## Implementation Report

Completed on 2026-09-28 from baseline `3e4f2afb9564ede87cd95f6ddb1b59195941cffc` on `fix/final-browser-smoke`.

- **Summary:** Configured project static discovery and collection output, removed the duplicate CSS source, added the authenticated Assistant link and root Login redirect, changed seed history notes to descriptive text while finding rows via tagged Appointments, preserved existing non-marker Notes during refresh, made the seed credential summary conditional without outputting the password, and corrected the 3 legacy marker Notes in the verified local demo database.
- **Files created:** `.agents/plans/021-final-browser-smoke-fixes.md`; `apps/ai_agent/test_browser_smoke.py`.
- **Files modified:** `README.md`; `apps/maintenance/management/commands/seed_demo_data.py`; `apps/maintenance/test_seed_demo_data.py`; `config/settings.py`; `config/urls.py`; `docs/demo-seed-data.md`; `templates/base.html`.
- **File deleted:** `apps/authentication/static/css/carvix.css`, the identical app-level copy that became ambiguous after project static discovery was enabled.
- **Acceptance criteria:** Staticfiles resolves one JavaScript and CSS source; Chat retains its namespaced endpoint, JSON fetch, same-origin credentials and CSRF token; authenticated Owner/Technician/Administrator navigation has Assistant and retains existing role links; anonymous Chat remains protected; `/` safely reaches Login and authenticated users follow Login-to-Profile; seeded Notes contain no internal record marker, existing seed records are corrected in place, counts remain stable, legitimate Notes remain visible; password summary is accurate in both states and never prints the secret.
- **Blank-Note regression:** `.venv/bin/python manage.py test apps.maintenance.test_seed_demo_data.DemoSeedCommandTests.test_repeated_command_run_populates_blank_note_and_keeps_it_stable -v 2` — PASS, 1/1.
- **Seed tests:** `.venv/bin/python manage.py test apps.maintenance.test_seed_demo_data -v 2` — PASS, 9/9, covering exact legacy-marker migration, deterministic blank Note fill and repeat stability, custom Note preservation across multiple runs, marker-like custom text, tag-only mismatch protection, object counts, and password output.
- **Focused tests:** `.venv/bin/python manage.py test apps.ai_agent.test_browser_smoke apps.maintenance.test_seed_demo_data -v 2` — PASS, 16/16.
- **Authentication tests:** `.venv/bin/python manage.py test apps.authentication -v 2` — PASS, 65/65.
- **AI Agent tests:** `.venv/bin/python manage.py test apps.ai_agent -v 2` — PASS, 118/118; no live Provider request.
- **Domain tests:** `.venv/bin/python manage.py test apps.appointments apps.vehicles apps.maintenance apps.inventory -v 1` — PASS, 169/169.
- **Full suite:** `.venv/bin/python manage.py test -v 1` — PASS, 352/352 in 824.321 seconds.
- **System/migration/whitespace checks:** PostgreSQL `pg_isready` accepted connections; `.venv/bin/python manage.py check` reported no issues; `.venv/bin/python manage.py makemigrations --check` reported no changes; `git diff --check` passed.
- **Static discovery / collection:** `.venv/bin/python manage.py findstatic js/agent_chat.js --verbosity 2` resolves exactly `/home/abdulrahman/Videos/carvix-smart-maintenance/static/js/agent_chat.js`; the focused test confirms the CSS has one project source. `.venv/bin/python manage.py collectstatic --noinput --dry-run` simulated 132 copies to the configured `staticfiles/` destination without errors or writing collected files.
- **Configured PostgreSQL demo data:** Before seed run, read-only counts matched exactly (5 users, 3 vehicles, 4 services, 6 appointments, 6 slots, 3 records, 3 parts, 2 maintenance parts) and 3 MaintenanceRecord Notes had the old marker. `.venv/bin/python manage.py seed_demo_data` completed successfully. Afterward those counts still matched, the 3 descriptive Notes were present, and `CARVIX_DEMO_SEED:v1:record:` appeared in 0 MaintenanceRecord Notes. The command output did not contain the configured password.
- **Browser verification:** HTTP results and limitation are recorded under Optional Browser Verification. The authenticated browser load remains unverified; use the manual steps there. The development server was stopped cleanly. No Chat message or live Gemini request was sent.
- **Migration/environment impact:** No Model or Migration file changed. `STATICFILES_DIRS` uses the existing `static/` directory; `STATIC_ROOT` is the ignored `staticfiles/` collection destination. No dependency, secret, or environment variable was added. README distinguishes local `DEBUG=True` static serving from production `DEBUG=False` static hosting.
- **Secret scan:** PASS across 161 tracked/non-ignored files; no common private-key, Google API-key, AWS access-key, GitHub-token, or Slack-token pattern found. `.env` is ignored and untracked; no Gemini key was present in the process. No secret value was printed.
- **Independent reviewer verdict:** APPROVABLE. An independent read-only reviewer confirmed new records receive descriptive Notes, only exact per-key legacy markers migrate, blank Notes are filled only after full identity validation, custom and marker-like Notes survive repeat seeding, and a tagged Appointment alone cannot authorize modification of a mismatched MaintenanceRecord. No Model, Migration, or scope change was introduced. No unresolved BLOCKER, HIGH, MEDIUM, or delivery-critical LOW finding remains.
- **Remaining risks:** The in-app browser did not render an authenticated Chat page because it had no authenticated session and blocked direct JavaScript-file navigation. Automated Chat template/fetch contract tests and local HTTP 200 checks passed; manual authenticated browser steps are provided above. A production `DEBUG=False` deployment must configure its own static-file server.
- **Deviations from plan:** Final pre-commit review identified blank Notes on a deterministic Demo record as an uncovered case. The correction verifies vehicle, service, technician, Appointment, service date, and mileage against the approved seed definition before modifying an existing record. It fills blank Notes, migrates exact legacy markers, preserves arbitrary nonblank Notes, and rejects mismatched records even if attached to a tagged Appointment. All requested PostgreSQL tests and checks passed. The initially drafted plan avoided changing the configured demo database. After a read-only check confirmed it was the expected local demo dataset with exactly 3 legacy record markers, the approved seed command was run once to satisfy the existing-record correction requirement; no counts changed and no deletion occurred. The optional authenticated browser observation is incomplete as documented; exact manual steps are provided. All changes remain unstaged and no commit, push, PR, or merge was made.
