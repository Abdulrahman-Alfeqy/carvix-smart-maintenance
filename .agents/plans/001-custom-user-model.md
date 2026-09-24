# Plan: Custom User Model in `apps/authentication`

## Metadata

- Status: DRAFT
- Related issue: N/A
- Owner: Abdelrahman Atef
- Reviewer: Arwa Mahmoud
- Branch: feature/custom-user
- Created: 2026-09-24
- Last updated: 2026-09-24
## Objective

Define and justify the implementation of the CARVIX custom Django `User` model inside the existing `apps/authentication` application, satisfying the approved SRS v1.0 `User` entity exactly:

- Fields: `id`, `username`, `email`, `password`, `role`, `is_active`, `date_joined`
- Constraints: unique `username`; unique and required `email`; `role` limited to Owner / Technician / Administrator; password hashed by Django
- Setting: `AUTH_USER_MODEL = "authentication.User"` configured before the project's first migration

This document is analysis and planning only. No source code, settings, models, admin, tests, migrations, or documentation are changed while this plan is DRAFT.

**Authoritative source for this plan:** `docs/CARVIX_SRS_Group6.docx`, Document Version 1.0, status "Initial Approved Baseline". Any conflicting four-role content in other documents (notably `docs/carvix-srs-v2.md`) is outdated for this task and is recorded below as a documentation follow-up only.

## Requirements Covered

From SRS v1.0 (`docs/CARVIX_SRS_Group6.docx`):

- **FR-01** — visitors register a Vehicle Owner account; password is hashed. *(This task supplies the model foundation: default role OWNER, hashed password storage.)*
- **FR-02** — login/logout for registered users. *(Foundation only: the model must remain compatible with Django's built-in auth views; views come in a later task.)*
- **FR-03** — authenticated users manage allowed profile fields. *(Foundation only: profile-editable fields live on this model.)*
- **FR-04** — Owner, Technician, Administrator roles are assigned and enforced. *(This task supplies the `role` field; endpoint enforcement/RBAC is a later task.)*
- **NFR-S04** — role checks prevent vertical privilege escalation. *(Model-level basis: safe role default, no privilege flags derived from role.)*
- **NFR-S06** — secrets from environment variables, excluded from Git. *(This task adds no secrets; existing violations are recorded as risks/follow-ups.)*
- **NFR-M01** — authentication stays separated in its own Django application. *(All changes live in `apps/authentication` plus two settings lines.)*
- SRS §6.2 `User` entity: `id, username, email, password, role, is_active, date_joined`; "Unique username/email; role choices; hashed password."
- AGENTS.md §5 step 2 and approved roadmap plan 000 step 2 — custom user model before the first production migration.

## Current-State Analysis

Verified by direct repository inspection on 2026-09-24:

1. **Project layout**: `config/` Django project; `apps/` is a real Python package (`apps/__init__.py` exists) containing `authentication`, `core`, `vehicle_management`, `ai_agent`. `manage.py` is stock — no `sys.path` manipulation — so apps are importable only by their full dotted path (e.g., `apps.authentication`).
2. **App registration**: `config/settings.py` `INSTALLED_APPS` contains only the six `django.contrib.*` apps. **The authentication app is NOT registered.** `AUTH_USER_MODEL` is not set.
3. **AppConfig name bug**: `apps/authentication/apps.py` declares `AuthenticationConfig.name = 'authentication'`. The importable dotted path of the app package is `apps.authentication`; no top-level `authentication` package exists, so registering `'authentication'` in `INSTALLED_APPS` would raise `ModuleNotFoundError`. The name must become `'apps.authentication'`.
4. **App label and `AUTH_USER_MODEL` validity**: with `name = 'apps.authentication'`, Django derives the default app label `authentication` (last dotted component). `AUTH_USER_MODEL = "authentication.User"` therefore references app label `authentication`, model class `User` — **valid for this structure once the app is registered and the config name is fixed**. No custom `label` override will be set.
5. **Migrations**: every `apps/*/migrations/` directory contains only `__init__.py`. **No real project migration files currently exist beyond `__init__.py`.**
6. **Local database state**: no `db.sqlite3` file exists at the repository root. No local SQLite database file was found. `DATABASES` in `config/settings.py` still contains Django's default SQLite configuration — this is incomplete scaffold configuration that must be replaced by PostgreSQL in the environment setup task (roadmap step 1). The actual PostgreSQL migration state has not yet been verified. PostgreSQL migration state must be verified safely before the first real migrate operation. This task must not create or modify any persistent database. (`showmigrations` was deliberately not run: it would either create an empty `db.sqlite3` against the scaffold SQLite config, or require a configured PostgreSQL connection — both are state changes this task forbids.)
7. **Timing**: greenfield state satisfies AGENTS.md §5 / roadmap step 2 — the custom user model lands before the first migration, so `AUTH_USER_MODEL` is painless and permanent.
8. **App files**: `apps/authentication/models.py`, `admin.py`, `tests.py` are stock Django placeholders — nothing to preserve or conflict with.
9. **URLs**: `config/urls.py` routes only `admin/` — no auth URLs exist yet (later task).
10. **Dependencies**: `Django==6.1.1` pinned. Django's built-in password hashing applies automatically via `set_password()` / `create_user()` — satisfies FR-01 hashing with zero custom code. `AbstractUser.REQUIRED_FIELDS = ['email']`, so `createsuperuser` already prompts for email, consistent with the required-email decision.
11. **PostgreSQL status**: PostgreSQL is the only approved project database. `config/settings.py` currently contains Django's default SQLite configuration — this is incomplete scaffold configuration, not an approved database choice. `psycopg` is absent from `requirements.txt`. PostgreSQL configuration is roadmap step 1 under its own plan. SQLite is not an approved CARVIX project database and must not be used as a development, testing, or migration fallback. The custom User model is database-backend-agnostic and unaffected by which backend is configured.
12. **Documentation conflict (recorded, not acted on)**: `docs/carvix-srs-v2.md` describes an outdated four-role system (`CLIENT / TECHNICIAN / MANAGER / ADMIN`) and extra `User` fields (`phone`, `avatar`). The authoritative SRS v1.0 defines exactly three roles (Owner, Technician, Administrator) and exactly the seven `User` fields listed above. See "Documentation follow-ups" under Risks.

### Approved decisions applied to this plan (resolved — no questions outstanding)

1. Exactly three roles with stored values `OWNER`, `TECHNICIAN`, `ADMINISTRATOR` and display labels Owner, Technician, Administrator.
2. Default role `OWNER` (FR-01 public registration creates Vehicle Owner accounts).
3. Public registration must never accept TECHNICIAN/ADMINISTRATOR from visitor input (enforced at form level in the later registration task; the model default is the safety net).
4. `email` is required and unique.
5. `username` remains the authentication identifier; no email login in this task.
6. Django built-in password hashing only; raw passwords are never stored or assigned.
7. Extend `AbstractUser`.
8. CARVIX `role` is separate from Django's `is_staff` / `is_superuser`; no automatic flag assignment from role (no custom manager forcing role or flags).
9. `AUTH_USER_MODEL = "authentication.User"` after verifying the app label (done — item 4 above).
10. Model created before the project's first migration (greenfield — item 6 above).
11. `makemigrations` is permitted after approval; `migrate` is forbidden in this task.
12. The approved SRS is not modified; conflicting documents are follow-up items only.

## Proposed Changes

Files expected to be created or modified **after this plan is APPROVED** (nothing is modified now):

1. **`config/settings.py`** (modify):
   - Add `'apps.authentication'` to `INSTALLED_APPS`.
   - Add `AUTH_USER_MODEL = 'authentication.User'`.
2. **`apps/authentication/apps.py`** (modify): `name = 'authentication'` → `name = 'apps.authentication'` (fixes the import path; default label stays `authentication`).
3. **`apps/authentication/models.py`** (modify) — the entire model addition:

   ```python
   from django.contrib.auth.models import AbstractUser
   from django.db import models


   class User(AbstractUser):
       class Role(models.TextChoices):
           OWNER = "OWNER", "Owner"
           TECHNICIAN = "TECHNICIAN", "Technician"
           ADMINISTRATOR = "ADMINISTRATOR", "Administrator"

       email = models.EmailField(unique=True)
       role = models.CharField(
           max_length=20,
           choices=Role.choices,
           default=Role.OWNER,
       )

       class Meta(AbstractUser.Meta):
           constraints = [
               models.CheckConstraint(
                   condition=models.Q(
                       role__in=("OWNER", "TECHNICIAN", "ADMINISTRATOR")
                   ),
                   name="authentication_user_valid_role",
               ),
           ]
   ```

   How each approved field is satisfied:
   - `id` — inherited implicit auto primary key (Django 6.x default `BigAutoField`).
   - `username` — inherited from `AbstractUser`; already `unique=True`; remains the login identifier.
   - `email` — overridden to add `unique=True`; required because `EmailField` defaults to `blank=False` (validated by forms/`full_clean()`); also in `REQUIRED_FIELDS` for `createsuperuser`.
   - `password` — inherited; always stored hashed via `set_password()`/`create_user()` (Django's configured password-hashing system).
   - `role` — the only genuinely new column; `TextChoices` provides application-level role definitions and model validation (`choices` field option, `full_clean()`); a `CheckConstraint` named `authentication_user_valid_role` provides database-level protection ensuring only `OWNER`, `TECHNICIAN`, or `ADMINISTRATOR` can be stored, even through `objects.create()`, `save()` without `full_clean()`, bulk operations, or any other backend path. Default `OWNER`.
   - `is_active` — inherited (`default=True`).
   - `date_joined` — inherited (`auto_now_add`-equivalent default `timezone.now`).
4. **`apps/authentication/admin.py`** (modify): register `User` with a `UserAdmin` subclass; add `role` to `fieldsets`, `add_fieldsets`, `list_display`, and `list_filter` so Administrators manage roles through Django Admin (per AGENTS.md §4: use Django Admin instead of custom admin pages).
5. **`apps/authentication/tests.py`** (modify): the test suite defined in Test Plan.
6. **`apps/authentication/migrations/0001_initial.py`** (created by `makemigrations` after approval — never hand-written).

No other apps, URLs, views, forms, or templates are touched in this task.

### Planned validation commands (listed for approval — NOT executed in planning mode)

The following commands may be run safely without initializing or modifying a persistent database:

```bash
python manage.py check
python manage.py makemigrations authentication
python manage.py makemigrations --check
```

The following commands require a correctly configured PostgreSQL test environment:

```bash
python manage.py test apps.authentication
python manage.py test
```

**Explicitly forbidden in this task:**
- `python manage.py migrate` — must NOT be run.
- `python manage.py migrate --plan` — must NOT be run.
- `python manage.py showmigrations` — must NOT be run.
- Using SQLite as a substitute for PostgreSQL to run tests.

If a designated PostgreSQL test environment is not correctly configured when implementation occurs, database-backed tests will be written but their execution will be reported as BLOCKED by the PostgreSQL environment task (roadmap step 1).

## Risks and Problems

- **Changing `AUTH_USER_MODEL` after migrations**: doing so mid-project requires migration surgery and possible data loss. Mitigated by timing: no real project migration files currently exist beyond `__init__.py`, no local SQLite database file was found, and the actual PostgreSQL migration state has not yet been verified. This task must not create or modify a persistent database; the setting lands before the first migration and is never changed afterwards.
- **Incorrect app label / dotted path**: registering `'authentication'` (or leaving `name = 'authentication'`) raises `ModuleNotFoundError`; a wrong label would silently invalidate `AUTH_USER_MODEL`. Mitigated by the `apps.py` fix plus `python manage.py check` and the settings test in the Test Plan.
- **Raw password assignment**: direct assignment (`user.password = "plain"`) stores plaintext. Mitigation: only `create_user()` / `set_password()` are used in code and tests; tests assert the stored password differs from the raw input, that `check_password` verifies correctly, and optionally that Django recognizes the stored value as a valid encoded password. Password tests are independent of the specific hashing algorithm.
- **Invalid role bypassing model validation**: Django `choices` and `full_clean()` only enforce role validity at the application level. Code paths that skip `full_clean()` — such as `objects.create()`, `save()` without validation, or bulk operations — could persist an invalid role. Mitigation: a `CheckConstraint` named `authentication_user_valid_role` is added to the `User` model `Meta`, enforcing the three approved role values (`OWNER`, `TECHNICIAN`, `ADMINISTRATOR`) at the database level. PostgreSQL will reject any `INSERT` or `UPDATE` that violates this constraint with an `IntegrityError`, regardless of the application path used. The Test Plan includes both a model-validation test (`full_clean()` rejects invalid roles) and a separate database-constraint test (persisting an invalid role raises `IntegrityError`).
- **Privilege escalation through role assignment (NFR-S04)**: if any public form or API ever accepts `role`, a visitor could self-assign ADMINISTRATOR. Mitigation: `role` defaults server-side to OWNER; the later registration form will exclude `role` entirely; role changes happen only via Django Admin (`is_staff`-gated). This task's tests verify the default and the validation boundary. The database `CheckConstraint` provides additional defense-in-depth.
- **Confusing ADMINISTRATOR with `is_staff` / `is_superuser`**: the CARVIX role is business authorization; Django flags are framework authorization. An `ADMINISTRATOR`-role user is **not** automatically staff or superuser, and a superuser is **not** automatically an ADMINISTRATOR. No manager overrides are introduced; the Test Plan asserts this separation explicitly.
- **Unique-email migration behavior**: adding `unique=True` to a populated table later could fail on duplicate existing rows. Mitigated by greenfield timing — the constraint exists from the very first migration, so no data deduplication can ever be needed.
- **Conflicting outdated documentation**: `docs/carvix-srs-v2.md` (four roles, extra fields) conflicts with the authoritative SRS v1.0. Risk: a future agent implements the outdated four-role system. Mitigation: recorded as documentation follow-up below; this plan forbids implementing it.
- **Existing secrets exposure (NFR-S06, pre-existing)**: `config/settings.py` currently contains a hardcoded `SECRET_KEY` and `DEBUG=True`. Not introduced by this task and out of its scope; must be resolved by the environment/PostgreSQL task (roadmap step 1). Recorded here for traceability.
- **`createsuperuser` ergonomics**: because `email` is in `REQUIRED_FIELDS`, superuser creation prompts for email — expected and consistent with the required-email decision; no code change needed.
- **Regression surface**: two settings lines and one app — no existing behavior exists to regress. Full-suite run is still required before marking IMPLEMENTED (AGENTS.md §10).

### Documentation follow-ups (record only — do NOT change documentation in this task)

1. `docs/carvix-srs-v2.md` describes an outdated four-role system (`CLIENT / TECHNICIAN / MANAGER / ADMIN`) and extra `User` fields (`phone`, `avatar`) — superseded by the approved SRS v1.0 for this project. The old role examples do not override the approved CARVIX roles (OWNER, TECHNICIAN, ADMINISTRATOR).
2. SRS v1.0 NFR-M01 and AGENTS.md §2 name the auth application `accounts`; the repository and this task use `apps/authentication`. This is a difference between theoretical application names in documentation and the applications that actually exist. Naming should be reconciled in documentation later.
3. AGENTS.md §2's app list (`accounts`, `vehicles`, `maintenance`, `appointments`, `inventory`) diverges from the actual packages (`authentication`, `core`, `vehicle_management`, `ai_agent`). These are differences between theoretical application names in documentation and the applications that actually exist.
4. Hardcoded `SECRET_KEY` / `DEBUG=True` in `settings.py` violates NFR-S06 — fix under the roadmap step-1 environment task.
5. `config/settings.py` contains Django's default SQLite scaffold configuration that must be replaced by PostgreSQL in the environment/PostgreSQL setup task (roadmap step 1). SQLite is not an approved CARVIX project database.

## Alternatives Considered

### Option A — Subclass `AbstractUser`, add `role` (recommended)

- Advantages: the approved field list (`id`, `username`, `email`, `password`, `is_active`, `date_joined`) is exactly `AbstractUser`'s built-in set — only `role` is new; password hashing, `create_user`/`create_superuser`, auth views (FR-02 later), and `UserAdmin` all work out of the box; smallest correct change; zero custom security-sensitive code; matches approved decision 7.
- Disadvantages: inherits a few columns the SRS does not list (`first_name`, `last_name`, `is_staff`, `is_superuser`, `groups`, `user_permissions`, `last_login`) — harmless, and `is_staff`/`is_superuser` are required anyway for Django Admin access; username-based login (explicitly approved, decision 5).

### Option B — Subclass `AbstractBaseUser` + `PermissionsMixin` from scratch

- Advantages: total schema control; no unused columns.
- Disadvantages: must hand-build the manager, admin forms, and password plumbing; re-verifies every auth integration; contradicts the approved field list (`username`, `date_joined` expected) and approved decision 7; unjustified complexity and security risk for the MVP — rejected.

*(A third idea — keeping `auth.User` with a separate profile table for `role` — was rejected: it fails the explicit `AUTH_USER_MODEL = "authentication.User"` requirement, contradicts SRS §6.2 placing `role` on `User`, and adds a join to every future role check.)*

## Recommended Approach

**Option A** — the smallest correct implementation for the approved CARVIX MVP:

- `User(AbstractUser)` with inner `Role(models.TextChoices)` (`OWNER`/`TECHNICIAN`/`ADMINISTRATOR`, labels Owner/Technician/Administrator).
- `role = CharField(choices=Role.choices, default=Role.OWNER)`.
- `email = EmailField(unique=True)` (required by default).
- A `CheckConstraint` named `authentication_user_valid_role` restricting the stored `role` to the three approved values at the database level, satisfying the program specification's requirement for database-level data integrity constraints (`CheckConstraint` where appropriate). `TextChoices` with `choices` provides application-level validation; the `CheckConstraint` provides defense-in-depth at the PostgreSQL level.
- No custom manager, no flag derivation, no extra fields.
- Fix `apps.py` name, register the app, set `AUTH_USER_MODEL`, wire `UserAdmin`, add tests, generate (but do not apply) the first migration.

Why: it satisfies every approved SRS field and constraint and decisions 1–12 with the least code, enforces role integrity at both application and database levels, keeps authentication isolated in its own app (NFR-M01), and leaves FR-02/FR-03 views and full RBAC (FR-04 enforcement) to their own later plans.

## Implementation Steps

1. Verify the authentication application path and Django app label. Inspect `apps/authentication/apps.py` and confirm the correct dotted path.
2. Fix `AuthenticationConfig.name` → `'apps.authentication'`.
3. Register the authentication application correctly: add `'apps.authentication'` to `INSTALLED_APPS` in `config/settings.py`.
4. Set `AUTH_USER_MODEL = 'authentication.User'` in `config/settings.py` (after verifying that `authentication` is the correct Django app label).
5. Implement `User(AbstractUser)` with `Role(TextChoices)` (`OWNER`, `TECHNICIAN`, `ADMINISTRATOR`), `role` field (default `OWNER`), unique `email`, and a `CheckConstraint` named `authentication_user_valid_role` restricting `role` to `("OWNER", "TECHNICIAN", "ADMINISTRATOR")` in `apps/authentication/models.py`.
6. Register `User` with a `UserAdmin` subclass in `apps/authentication/admin.py` (role in fieldsets/add_fieldsets/list_display/list_filter).
7. Implement the Test Plan suite in `apps/authentication/tests.py`.
8. Run `python manage.py check` — expect "no issues".
9. Generate the authentication migration: `python manage.py makemigrations authentication`.
10. Inspect `apps/authentication/migrations/0001_initial.py` to verify correctness — confirm the role `CheckConstraint` (`authentication_user_valid_role`) and the three literal role values (`"OWNER"`, `"TECHNICIAN"`, `"ADMINISTRATOR"`) are present in the generated migration.
11. Run `python manage.py makemigrations --check` — expect "no changes detected."
12. Determine whether a safe PostgreSQL testing environment is correctly configured.
13. If PostgreSQL is configured with safe test credentials: run `python manage.py test apps.authentication`, then `python manage.py test` (full suite, AGENTS.md §10).
14. If PostgreSQL is not configured: keep the tests written but report their execution as BLOCKED by the PostgreSQL environment task (roadmap step 1). Do not substitute SQLite.
15. **Never run `python manage.py migrate` in this task.**
16. Report per AGENTS.md §13; mark IMPLEMENTED only after steps 8–11 succeed and either step 13 passes or step 14 is documented.

## Test Plan

Planned tests in `apps/authentication/tests.py` (Django `TestCase` and `TransactionTestCase`).

**Important:** All tests in this section are database-backed. They require a correctly configured PostgreSQL test environment. If PostgreSQL is not configured, these tests will be written but their execution will be reported as BLOCKED by the PostgreSQL environment task. SQLite must never be substituted.

1. **Regular user creation** — `create_user(username=..., email=..., password=...)` succeeds; `is_active` is True; `date_joined` auto-populated.
2. **Default role** — a user created without an explicit role has `role == User.Role.OWNER`.
3. **Explicit TECHNICIAN role** — user saved with `role=User.Role.TECHNICIAN` passes `full_clean()` and persists.
4. **Explicit ADMINISTRATOR role** — user saved with `role=User.Role.ADMINISTRATOR` passes `full_clean()` and persists.
5. **Invalid role rejection (model validation)** — `full_clean()` on `role="MANAGER"` (or any non-enum value) raises `ValidationError`. This tests the application-level `TextChoices` validation.
6. **Invalid role rejection (database constraint)** — attempting to persist a user with an invalid role value (e.g., `"MANAGER"`) by bypassing `full_clean()` (e.g., via direct `save()` or `objects.create()`) raises `django.db.IntegrityError`. This tests the database-level `CheckConstraint` (`authentication_user_valid_role`). This test must use `TransactionTestCase` (or equivalent transaction-safe Django test handling) to correctly handle the `IntegrityError` without corrupting the test transaction. This test must run only against the designated PostgreSQL test environment, never against SQLite, and must be marked BLOCKED if PostgreSQL is not configured.
7. **Required email validation** — `full_clean()` with a blank email raises `ValidationError`.
8. **Unique email validation** — creating a second user with an existing email fails validation (and/or raises `IntegrityError` on save).
9. **Password hashing** — stored `password` differs from the raw input. The test must be independent of the hashing algorithm: do not require a specific encoded-password prefix such as `pbkdf2_sha256$`. Optionally assert that Django recognizes the stored value as a valid encoded password (e.g., via `django.contrib.auth.hashers.identify_hasher(user.password)`).
10. **Password verification using `check_password`** — `check_password(correct_password)` returns `True`; `check_password(wrong_password)` returns `False`.
11. **Superuser creation** — `create_superuser(...)` succeeds with `is_staff=True`, `is_superuser=True` (and email required by `REQUIRED_FIELDS`).
12. **Separation between role, `is_staff`, and `is_superuser` (NFR-S04)** — a `create_user` user with `role=User.Role.ADMINISTRATOR` still has `is_staff=False` and `is_superuser=False`; a superuser's business `role` is independent of its Django flags (the superuser is not automatically an ADMINISTRATOR, and an ADMINISTRATOR is not automatically a superuser).
13. **Correct `AUTH_USER_MODEL`** — `settings.AUTH_USER_MODEL == "authentication.User"` and `get_user_model()` returns the `User` class from the `authentication` app.
14. **Django system checks** — `call_command("check")` completes with no errors against the configured custom user model. *(This test can also run safely without a database, but is included in the test suite for completeness.)*
15. **Correct result from `get_user_model()`** — `get_user_model()` returns `apps.authentication.models.User` (the class, not a proxy or the default `auth.User`).
16. **Correct authentication application label** — the `User` model's `_meta.app_label` is `'authentication'`.

## Migration and Environment Impact

- **Migrations**: one auto-generated file, `apps/authentication/migrations/0001_initial.py`, produced by `makemigrations` after approval. No real project migration files currently exist beyond `__init__.py`. The generated migration must be inspected to confirm it contains the `authentication_user_valid_role` `CheckConstraint`. The actual PostgreSQL migration state has not yet been verified. PostgreSQL migration state must be verified safely before the first real migrate operation. `migrate` is **not** run in this task. This task must not create or modify any persistent database. Rollback before any future `migrate` = delete the generated migration file.
- **Settings**: two additive lines (`INSTALLED_APPS` entry, `AUTH_USER_MODEL`). No existing behavior is altered.
- **Dependencies / environment variables**: none added; no `.env` changes; nothing installed.
- **Database**: this task does not initialize, create, or modify any database. PostgreSQL is the only approved project database. The existing SQLite scaffold configuration in `settings.py` is not used and is not an approved fallback.
- **Git**: work stays on `feature/custom-user`; Conventional Commits (e.g., `feat: add custom user model with role field`); no commit or push occurs during planning.
- **Out of scope (other plans)**: PostgreSQL configuration, env-based secrets (NFR-S06 fix), registration/login/profile views (FR-01/02/03 endpoints), RBAC enforcement (FR-04), `apps/core` AppConfig name bug.

## Open Questions

None. All material decisions — number of roles, role names and stored values, default role, email uniqueness and requirement, username-vs-email login, `AbstractUser` vs `AbstractBaseUser`, and the ADMINISTRATOR-vs-superuser separation — were resolved by the approved SRS v1.0 and the pre-approved decisions recorded in Current-State Analysis. Repository inspection discovered no new blocking conflict; documentation divergences are recorded as follow-ups only.

## Approval

- Decision: PENDING
- Approved by: <name>
- Approval date: <YYYY-MM-DD>

Implementation must not begin while Status is `DRAFT` or Decision is `PENDING`.

## Implementation Report

Complete this section after implementation:

- Summary:
- Files changed:
- Tests executed:
- Test results:
- Migration/environment changes:
- Security checks:
- Remaining risks:
- Deviations from plan:
