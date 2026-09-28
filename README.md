# CARVIX

CARVIX is a Django and PostgreSQL vehicle-maintenance management application for Owners, Technicians, and Administrators. This repository contains the normal web workflows for vehicles, maintenance, appointments, technician work, inventory records, and read-only AgentActionLog inspection.

## Requirements

- Python 3.12 or newer
- PostgreSQL
- Dependencies pinned in [`requirements.txt`](requirements.txt)

The checked-in dependency file currently pins Django 6.1.1 and `psycopg[binary]` 3.3.6. Use a supported PostgreSQL version available in your environment; the project requires a running PostgreSQL server and does not configure SQLite as a fallback.

## Local installation (Windows PowerShell)

From the repository root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run the virtual-environment interpreter directly, for example `.venv\Scripts\python.exe manage.py check`.

## PostgreSQL and environment configuration

1. Start PostgreSQL and create a local role and database. For example, from `psql` as a PostgreSQL administrator, replace the password placeholder with a locally chosen secret:

   ```sql
   CREATE USER carvix_user WITH PASSWORD 'choose-a-local-password';
   CREATE DATABASE carvix_db OWNER carvix_user;
   ```

2. Copy the example environment file and edit the local copy:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Set `SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` in `.env` to match your local setup. `POSTGRES_HOST` and `POSTGRES_PORT` default to `localhost` and `5432` in the Django settings. `ALLOWED_HOSTS` defaults to `localhost,127.0.0.1`.

4. To enable the authenticated CARVIX assistant, set `GEMINI_API_KEY` in the server-side `.env` using a key from [Google AI Studio](https://aistudio.google.com/app/apikey). `GEMINI_MODEL` defaults to the SRS model alias `gemini-flash-latest`; `GEMINI_TIMEOUT_SECONDS` defaults to 20 and accepts values from 1 through 30. Keep the key out of source control, browser code, screenshots, and shared logs. Without a key, Chat returns a safe unavailable response while manual booking and other non-AI workflows remain available.

5. For local `runserver` use only, set `DEBUG=True` in `.env` so Django's development static-file handler serves the stylesheet. Keep `DEBUG=False` for deployed environments and configure a production static-file server there. Never commit `.env` or reuse local demo secrets in production; `.env` is ignored by Git.

## Migrations

Apply the checked-in migrations to your configured local PostgreSQL database:

```powershell
python manage.py migrate
```

To check whether model changes require new migrations:

```powershell
python manage.py makemigrations --check
```

## Optional demo data

The deterministic seed command can be run locally after migrations:

```powershell
python manage.py seed_demo_data
```

It creates or refreshes reserved demo records without flushing the database. Demo usernames are `demo.owner.one`, `demo.owner.two`, `demo.technician.one`, `demo.technician.two`, and `demo.administrator`. Seeded accounts have unusable passwords by default. If interactive demo sign-in is needed, set a unique local-only password in the current PowerShell session before seeding:

```powershell
$env:CARVIX_DEMO_PASSWORD = '<choose-a-local-only-password>'
python manage.py seed_demo_data
Remove-Item Env:CARVIX_DEMO_PASSWORD
```

The command does not print the password. Do not paste a real password into this README, source control, a shared terminal transcript, or a production environment. See [`docs/demo-seed-data.md`](docs/demo-seed-data.md) for the dataset, idempotency, collision handling, and limitations. Do not run the seed command against a shared database without its owner's approval.

## Run the application

With PostgreSQL running, dependencies installed, migrations applied, and local `.env` configured:

```powershell
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. Sign in and use the role-aware navigation/profile entry points. When Gemini is configured, authenticated Chat can request the three registered CARVIX Tools; Django validates and executes each request through the central Tool Registry.

## Tests and checks

Run checks and the full test suite against the configured PostgreSQL database:

```powershell
python manage.py check
python manage.py makemigrations --check
python manage.py test -v 2
```

Focused suites:

```powershell
python manage.py test apps.authentication.tests apps.vehicles.tests apps.appointments.tests -v 2
python manage.py test apps.maintenance.test_seed_demo_data -v 2
```

PostgreSQL-specific constraint and concurrency tests require PostgreSQL. Do not substitute SQLite when those tests cannot connect.

## Architecture overview

CARVIX uses Django's Model–View–Template structure. Django templates and general CSS provide the browser presentation; views handle HTTP requests and role checks; forms validate submitted fields; selectors and services hold reusable read logic and domain operations; Django's ORM persists data to PostgreSQL. Ownership and role authorization are enforced by backend views/services, not by hidden navigation links.

The current Django applications are:

- `apps.authentication` — custom user roles, registration, sign-in, profile.
- `apps.vehicles` — Owner-scoped vehicle pages.
- `apps.maintenance` — service definitions, maintenance history/due-service logic, and demo seed command.
- `apps.appointments` — slots, Owner booking and appointment pages, assignment, Technician workflow.
- `apps.inventory` — spare parts and maintenance usage records.
- `apps.ai_agent` — authenticated Chat, safe role-scoped context, the bounded Gemini Provider/Tool loop, central AgentActionLog recording, and Administrator inspection.

## Documentation and project paths

- Authoritative requirements: [`docs/CARVIX_SRS_Group6.docx`](docs/CARVIX_SRS_Group6.docx)
- Documentation source policy: [`docs/README.md`](docs/README.md)
- Supporting architecture: [`docs/architecture.md`](docs/architecture.md)
- Supporting ERD: [`docs/erd.md`](docs/erd.md) and [`docs/ERD.jpeg`](docs/ERD.jpeg)
- Supporting journeys: [`docs/user-journeys.md`](docs/user-journeys.md)
- Demo dataset instructions: [`docs/demo-seed-data.md`](docs/demo-seed-data.md)
- Demo script and checklists: [`docs/demo-runbook.md`](docs/demo-runbook.md)
- Shared development instructions: [`AGENTS.md`](AGENTS.md)
- Task plans: [`.agents/plans/`](.agents/plans/)
- Shared templates: [`templates/`](templates/)
- General stylesheet: [`static/css/carvix.css`](static/css/carvix.css)
- Django app static-file discovery copy: [`apps/authentication/static/css/carvix.css`](apps/authentication/static/css/carvix.css)

The stylesheet is mirrored under the installed authentication app because the repository-root `static/` directory is not listed in `STATICFILES_DIRS`. Keep the two stylesheet files identical; this avoids a settings change while allowing Django's app static-file finder and `collectstatic` to discover the asset.

The DOCX SRS is authoritative. The architecture, ERD, and journey files are supporting references and may contain historical details; where they conflict with the SRS or current implementation, do not treat them as the system contract.
