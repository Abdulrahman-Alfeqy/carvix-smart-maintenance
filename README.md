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

5. For local `runserver` use only, set `DEBUG=True` in `.env` so Django's development static-file handler serves project assets. The project-level `static/` directory is registered for discovery; `collectstatic` gathers those assets into `STATIC_ROOT` for deployment. Keep `DEBUG=False` in deployed environments and configure a production static-file server or equivalent there; Django's development static handler is not a production serving solution. Never commit `.env` or reuse local demo secrets in production; `.env` is ignored by Git.

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

Open `http://127.0.0.1:8000/accounts/login/` to sign in; a successful sign-in redirects to the profile page and its role-aware entry points. When Gemini is configured, authenticated Chat can request the three registered CARVIX Tools; Django validates and executes each request through the central Tool Registry.

## Manual and AI-assisted workflows

The manual Owner workflow supports vehicle management, maintenance history and due-service guidance, active-slot discovery, and appointment booking. The Administrator assigns an available Technician; that Technician can start and complete assigned work, record parts used, and update maintenance history. Django views, forms, selectors, and services enforce these rules independently of the AI Provider.

The authenticated assistant exposes exactly these Tools through the allowlisted Django Registry:

| Tool | Purpose | Access |
| --- | --- | --- |
| `check_required_maintenance` | Check due or overdue maintenance for one owned vehicle. | Owner's own vehicles |
| `list_available_service_slots` | List active future slots that still have capacity. | Owner, Technician, Administrator |
| `book_maintenance_appointment` | Book for an owned vehicle after explicit confirmation. | Owner only |

The assistant receives the configured service names and IDs needed to select a valid service, plus role-scoped context. It cannot query the database or execute Tools itself. Django validates every call, binds it to the signed-in user, enforces permissions, and records registered Tool attempts. Gemini must be configured for live Chat; without a key, Chat returns a safe unavailable response and manual workflows continue to work. The SDK is installed with `python -m pip install -r requirements.txt`.

Slot results include globally eligible slots because the current data model does not associate slots with a service type. The optional `preferred_date` Tool argument is validated but does not filter results. Chat history is request-local and is not persisted. Owner appointment cancellation is deferred (FR-15 is Should and its eligibility rules are not defined). See [`docs/final-traceability.md`](docs/final-traceability.md) for the requirement-to-code map and [`docs/demo-runbook.md`](docs/demo-runbook.md) for the optional read-only AI demo.

Other excluded scope remains out of the MVP: payments, maps/GPS, mobile or voice clients, WebSockets, RAG/embeddings/vector storage, multiple agents, predictive ML, multiple service-center branches, and supplier/financial systems.

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
- Documentation index and source policy: [`docs/README.md`](docs/README.md)
- Final approved system architecture diagram: [`docs/system architecture.jpeg`](docs/system%20architecture.jpeg)
- Final approved ERD diagram: [`docs/ERD.jpeg`](docs/ERD.jpeg)
- Final approved workflow diagram: [`docs/Workflow diagram.jpeg`](docs/Workflow%20diagram.jpeg)
- Demo dataset instructions: [`docs/demo-seed-data.md`](docs/demo-seed-data.md)
- Demo script and checklists: [`docs/demo-runbook.md`](docs/demo-runbook.md)
- Final SRS traceability: [`docs/final-traceability.md`](docs/final-traceability.md)
- Shared development instructions: [`AGENTS.md`](AGENTS.md)
- Task plans: [`.agents/plans/`](.agents/plans/)
- Shared templates: [`templates/`](templates/)
- General stylesheet: [`static/css/carvix.css`](static/css/carvix.css)

Project assets live under `static/` and are discovered through `STATICFILES_DIRS`; `STATIC_ROOT` is the `staticfiles/` destination populated by `collectstatic`. Local `DEBUG=True` runserver behavior is for development, while deployments with `DEBUG=False` must serve collected assets through a configured static-file server or equivalent.

The DOCX SRS is the authoritative requirements document, and the three JPEG files above are the final approved diagrams. Historical Markdown diagram drafts were removed because they conflicted with the SRS, the approved diagrams, and the current implementation; do not reintroduce requirements, roles, entities, fields, Tools, or workflows that are absent from the SRS and the repository.
