# CARVIX AI Development Instructions

## 1. Purpose

This file is the single source of working instructions for every AI assistant, coding agent, and team member working on CARVIX.

Before planning, coding, reviewing, testing, or changing the project, read this file and the approved plan for the current task.

If an AI tool does not automatically read `AGENTS.md`, the user must attach this file or paste its contents into the conversation.

---

## 2. Project Summary

CARVIX is a Django web application for vehicle maintenance management.

The system allows vehicle owners to manage vehicles and maintenance appointments. A controlled AI assistant can review permitted maintenance data and book suitable appointments only through validated Django backend tools after explicit user confirmation.

### Core stack

- Python 3.12+
- Django MVT
- PostgreSQL
- HTML5 and CSS3
- JavaScript ES6+
- External LLM with controlled tool calling

### User roles

- Vehicle Owner
- Technician
- Administrator

### Main Django applications

- `accounts`
- `vehicles`
- `maintenance`
- `appointments`
- `inventory`
- `ai_agent`

---

## 3. Sources of Truth

Use the following precedence when information conflicts:

1. The approved CARVIX SRS and formal requirements in `docs/`.
2. Accepted project architecture and diagrams in `docs/`.
3. This `AGENTS.md` file.
4. The approved plan for the current task in `.agents/plans/`.
5. Existing tested behavior, unless the approved task explicitly changes it.

Never invent project requirements, roles, models, features, or architecture.

If a real conflict exists between sources, stop and explain it to the user before implementation.

---

## 4. Scope Rules

Keep CARVIX limited to the approved MVP.

Do not add any of the following unless the user explicitly approves a scope change:

- RAG
- Vector databases
- Embeddings
- Multiple AI agents inside the CARVIX product
- Voice assistant
- Mobile application
- Maps or GPS
- Online payments
- WebSockets
- Predictive machine-learning models
- Multiple service-center branches
- Complex supplier or financial systems

Use Django Admin where appropriate instead of building unnecessary custom administration pages.

---

## 5. Required Development Order

Follow this sequence unless an approved plan explicitly justifies a change:

1. Project environment and PostgreSQL configuration.
2. Custom user model before the first production migration.
3. Authentication and the three roles.
4. Core database models.
5. Normal application workflow without AI.
6. Ownership checks and RBAC.
7. Chat interface.
8. Read-only maintenance-check tool.
9. Confirmed appointment-booking tool.
10. LLM and tool integration.
11. Tests, seed data, documentation, and demo preparation.

Do not implement AI booking before manual booking and its authorization rules work correctly.

---

## 6. Planning Rule

Every meaningful task must have one Markdown plan inside:

`.agents/plans/`

Use `.agents/PLAN_TEMPLATE.md` as the template.

A plan has one of these statuses:

- `DRAFT`: analysis only; implementation is not allowed.
- `APPROVED`: implementation may begin.
- `IMPLEMENTED`: implementation and required tests are complete.
- `BLOCKED`: progress requires a human decision or missing dependency.

Do not create multiple competing plans for the same GitHub issue or task.

Small read-only actions do not need a plan, including inspecting files, searching the repository, checking Git status, or running existing non-destructive tests.

---

## 7. Required AI Workflow

Before changing source code, database schemas, dependencies, configuration, architecture, or user-visible behavior:

1. Inspect the relevant repository files. Do not assume their contents.
2. Read the relevant requirements and current task plan.
3. Analyze the current implementation.
4. Identify risks, edge cases, security concerns, migration impact, integration conflicts, and possible regressions.
5. Propose reasonable alternatives with advantages and disadvantages.
6. Recommend one approach and explain the reason.
7. Create or update the plan in `.agents/plans/` with status `DRAFT`.
8. Ask only focused questions whose answers materially affect behavior, architecture, security, data, scope, or user experience.
9. Do not modify implementation files until the user or assigned reviewer changes the plan status to `APPROVED`.

After approval:

1. Follow the approved plan.
2. Do not repeatedly ask permission for routine implementation steps, formatting, imports, or non-destructive test commands.
3. Make the smallest coherent change that satisfies the approved requirements.
4. Run the relevant tests.
5. Report changed files, test results, remaining risks, and any deviations from the plan.
6. Change the plan status to `IMPLEMENTED` only when implementation and required tests are complete.

If implementation reveals a material conflict with the approved plan, stop, document the conflict, provide alternatives, and ask for a new decision.

---

## 8. Architecture and Coding Rules

- Keep views thin.
- Put reusable business rules in services or appropriate domain functions.
- Use Django forms or explicit schemas for validation.
- Use the Django ORM. Do not use raw SQL for AI tools.
- Use `request.user` as the identity source.
- Never accept `user_id` from an AI-generated tool call.
- Filter owner data by ownership before returning objects.
- Filter technician work by assignment.
- Enforce permissions on the backend, not only in templates or JavaScript.
- Use `transaction.atomic()` for booking and multi-write inventory operations.
- Keep secrets in environment variables.
- Never commit `.env`, credentials, API keys, tokens, database dumps, or private user data.
- Do not add a dependency when the standard library or an existing dependency is sufficient.
- Do not silently change public behavior, database contracts, or accepted requirements.
- Keep code readable and explain non-obvious business rules.

---

## 9. AI-Agent Security Rules

CARVIX's product AI assistant must:

- Receive only the minimum permitted context.
- Call only allowlisted backend tools.
- Never access PostgreSQL directly.
- Never execute raw SQL.
- Never claim success unless the backend returns success.
- Never access another owner's vehicle.
- Never perform Administrator actions for an Owner or Technician.
- Ask for explicit user confirmation before creating, cancelling, deleting, or modifying data.
- Validate every tool argument server-side.
- Recheck permissions inside every tool.
- Return structured success or failure results.
- Log every attempted tool execution safely.
- Avoid exposing stack traces, secrets, or sensitive object details.

The primary tools are:

- `check_required_maintenance`
- `list_available_service_slots`
- `book_maintenance_appointment`

---

## 10. Testing Rules

Every behavior change requires tests appropriate to its risk.

At minimum, consider:

- Successful behavior
- Invalid input
- Anonymous access
- Incorrect role
- Cross-owner access
- Modified URL or object identifier
- Missing objects
- Duplicate booking
- Full or expired slot
- Missing AI confirmation
- Unauthorized tool call
- Transaction rollback
- LLM or external-service failure

Testing requirements:

- Inspect existing tests before adding new ones.
- Run the smallest relevant test set first.
- Run the full project suite before marking a plan `IMPLEMENTED`.
- Never delete, skip, or weaken a valid test merely to make the suite pass.
- Never state that tests passed unless they were actually executed.
- Report the exact command and result.

Use the test command documented by the repository. If none exists, use the appropriate Django test command for the current environment and document it in the plan.

---

## 11. Git and Team Workflow

- `main` contains stable demonstrable code.
- `develop` integrates reviewed work.
- Do not implement features directly on `main`.
- Use short-lived branches such as `feature/`, `fix/`, `docs/`, `test/`, or `chore/`.
- One person owns implementation for a task; the other reviews it.
- Do not let two AI agents independently edit the same feature at the same time.
- Link each implementation to one issue and one plan.
- Use pull requests and require teammate review before merging.
- Keep commits focused and use Conventional Commits.

Examples:

- `feat: add vehicle registration flow`
- `fix: prevent duplicate slot booking`
- `test: add ownership permission tests`
- `docs: document agent tool schemas`
- `chore: configure PostgreSQL environment`

Before opening a pull request, report:

- What changed
- Why it changed
- How to test it
- Test results
- Migration impact
- Environment-variable impact
- Known limitations

---

## 12. Definition of Done

A task is complete only when:

- The approved acceptance criteria are satisfied.
- Required permission and ownership checks exist.
- Relevant automated tests pass.
- The full suite has been run or any inability is documented.
- Migrations are correct when required.
- No secrets or private data are committed.
- User-visible success and failure states are handled.
- Documentation is updated when behavior or setup changes.
- The implementation matches the approved plan.
- A teammate can explain and reproduce the change.

---

## 13. Required Final Report from Any AI

After implementation, respond with:

1. Summary of the completed work.
2. Files created, modified, or deleted.
3. Requirements and acceptance criteria covered.
4. Tests executed and exact results.
5. Migration or environment changes.
6. Security considerations checked.
7. Remaining limitations or risks.
8. Any deviation from the approved plan.
