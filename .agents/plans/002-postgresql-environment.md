# Plan: PostgreSQL Environment Configuration

## Metadata

- Status: APPROVED
- Related issue: N/A
- Owner: Abdelrahman Atef
- Reviewer: Arwa Mahmoud
- Branch: chore/postgresql-setup
- Created: 2026-09-24
- Last updated: 2026-09-24

## Objective

Configure CARVIX to use PostgreSQL securely via environment variables, removing SQLite entirely. Establish a safe local development database and a clean test database environment, allowing the currently blocked custom User tests to run successfully without exposing credentials or development data.

## Requirements Covered

- PostgreSQL is the only approved CARVIX project database.
- SQLite must not be retained as a fallback.
- Django ORM must be used.
- Database credentials and Django secrets must be read from environment variables.
- `.env` must never be committed.
- Test-database workflow must isolate data correctly.

## Current-State Analysis

1. **Declared Python version:** 3.12 (from README.md).
2. **Required Django version:** 6.1.1 (from requirements.txt).
3. **Current DATABASES config:** Hardcoded to `django.db.backends.sqlite3` in `config/settings.py`.
4. **PostgreSQL driver:** Not listed in `requirements.txt`.
5. **.env.example existence:** Exists, containing safe placeholders (`SECRET_KEY`, `DEBUG`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`).
6. **.gitignore exclusions:** Excludes `.env`, `db.sqlite3`, and `__pycache__`/`*.pyc`, but does NOT exclude PostgreSQL database dumps (`*.sql`, `*.dump`).
7. **Hardcoded SECRET_KEY:** A hardcoded Django development SECRET_KEY currently exists in config/settings.py. Its value must not be copied into plans, logs, comments, reports, commands, screenshots, or Git history.
8. **DEBUG configuration:** Hardcoded to `True` in `config/settings.py`.
9. **Existing PostgreSQL config:** None exists.
10. **Custom User status:** The `0001_initial.py` migration exists but is unapplied. Tests are written but blocked because PostgreSQL is not configured.

## Proposed Changes

Expected files to change:
- `requirements.txt`: Add the PostgreSQL driver and `python-dotenv`.
- `config/settings.py`: Load secrets dynamically; switch `DATABASES` engine to PostgreSQL.
- `.env.example`: Standardize variable names and placeholders.
- `.gitignore`: Ignore database dumps (`*.sql`, `*.dump`).
- `.agents/plans/002-postgresql-environment.md`: This plan.
- `.agents/plans/001-custom-user-model.md`: Update implementation report and status later.

## Environment-Variable Contract

The standard library `os.environ` does not automatically load variables
from a `.env` file. CARVIX will use `python-dotenv` to load the local
`.env` file during development.

The real `.env` file must remain untracked and must never be committed.

### Required variables

- `SECRET_KEY`: Required. Must not have a default value in source code.
  The real value must be generated locally and stored only in `.env`.

- `POSTGRES_DB`: Required. Must not have a default value in source code.
  The approved local development identifier is `carvix_db`.

- `POSTGRES_USER`: Required. Must not have a default value in source
  code. The approved local development identifier is `carvix_user`.

- `POSTGRES_PASSWORD`: Required. Must not have a default value in source
  code. The real password must be created locally and stored only in
  `.env`.

### Optional variables with safe local defaults

- `DEBUG`: Optional. Safe default: `False`. The value must be parsed
  case-insensitively and may recognize `1`, `true`, `yes`, and `on` as
  enabled values. Any other or missing value must resolve to `False`.

- `ALLOWED_HOSTS`: Optional for local development. Safe default:
  `localhost,127.0.0.1`. Values must be split by commas, trimmed, and
  filtered to remove empty entries. Parsing must never produce `[""]`.

- `POSTGRES_HOST`: Optional for local development. Safe default:
  `localhost`.

- `POSTGRES_PORT`: Optional for local development. Safe default: `5432`.

Missing required variables must cause a clear configuration error
without printing or exposing secret values.

The local `.env` file will contain the real development credentials and
must remain excluded from version control. The committed `.env.example`
file will contain only safe placeholders and non-secret example values.

## Alternatives Considered

- **`psycopg2-binary`**: Older driver, widely used but lacks some modern features.
- **`psycopg`**: Modern Python driver but might require local build tools to compile dependencies.
- **`psycopg[binary]`**: Modern driver with pre-compiled binaries included.

## Recommended Approach

Use **`psycopg[binary]`**. It minimizes local system build dependencies and ensures a smooth installation process while providing all the modern features needed for Django 6.1.1 and Python 3.12. We will also add **`python-dotenv`** to parse the `.env` file.

## Security Risks

- **Hardcoded SECRET_KEY exposure**: Addressed by strictly using environment variables.
- **Accidental `.env` commits**: Guarded by `.gitignore`.
- **Exposing DB credentials in terminal history**: Avoid placing passwords directly into shell commands.
- **Committing DB Dumps**: Add `*.sql` and `*.dump` to `.gitignore`.
- **Unsafe DEBUG parsing**: Addressed by case-insensitive boolean parser.
- **Overly permissive ALLOWED_HOSTS**: Handled by robust string splitting without empty entries.
- **Running destructive commands against wrong DB**: Addressed by requiring explicit human approval for migrations and checking target DB.

## Implementation Steps

1. Verify Python and Django versions.
2. Verify PostgreSQL tools and service readiness.
3. Verify dependency compatibility.
4. Update `requirements.txt` (add `psycopg[binary]` and `python-dotenv`).
5. Install approved dependencies.
6. Update `.gitignore`.
7. Update `.env.example`.
8. Create the local untracked `.env`.
9. Update `config/settings.py`.
10. Verify only non-secret configuration values.
11. Verify PostgreSQL readiness.
12. Run `python manage.py check`.
13. Run `showmigrations` only after PostgreSQL is confirmed and after explicit human approval. (Note clearly that `showmigrations` connects to the configured database and is not an offline command).
14. Confirm the target database.
15. Run `migrate` only after explicit human approval.
16. Run authentication tests.
17. Run the complete test suite.
18. Verify no SQLite fallback was used.
19. Verify no secrets are staged.

## PostgreSQL Role and Database Setup Strategy

Use these non-secret local identifiers:
- POSTGRES_DB=`carvix_db`
- POSTGRES_USER=`carvix_user`
- POSTGRES_HOST=`localhost`
- POSTGRES_PORT=`5432`
Secret values (password) will be generated locally and stored only in `.env`. The database user must have `CREATEDB` permissions.

## Migration Plan

- The target database must be confirmed before running `migrate`.
- `showmigrations` will connect to the PostgreSQL instance to verify the state.
- Both `showmigrations` and `migrate` require explicit human approval.

## Test-Database Strategy

- Allow Django to create and destroy its PostgreSQL test database automatically. It is not required to have the exact name `test_carvix_db`.
- Verify that the backend is PostgreSQL.
- Verify that the test database is separate from the development database.
- Verify that the PostgreSQL role has `CREATEDB` permission.
- Verify that development data is not modified.

## Rollback and Failure Handling

If failures occur, do not automatically uninstall packages, delete SQLite files, or delete PostgreSQL data. Instead:
- Stop on failure.
- Inspect the error.
- Revert uncommitted configuration changes when appropriate.
- Recreate the virtual environment from known-good requirements if necessary.
- Inspect Git status before deleting any file.
- Delete an accidental SQLite file only after explicit human approval.
- Never delete PostgreSQL data automatically.

## Branch and PR Strategy

- **Current branch:** `chore/postgresql-setup`
- **Parent branch:** `feature/custom-user`
- **Future PR base:** `feature/custom-user`
- PR #7 remains Draft. This branch must not target `main` directly.

## Definition of Done

- `psycopg[binary]` and `python-dotenv` are installed.
- PostgreSQL correctly configured via `.env`.
- `.gitignore` updated.
- Custom User tests successfully execute against a real PostgreSQL test database.
- No SQLite fallback is used.
- No secrets are tracked.

## Open Questions

None blocking. Local secret values will be created securely during implementation.

## Approval

- Decision: APPROVED
- Approved by: Abdelrahman Atef
- Approval date: 2026-09-24
- Approval note: Self-approved by the task owner due to the project schedule. Teammate review remains required before merging into `feature/custom-user`.

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
