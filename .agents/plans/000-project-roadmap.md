# Plan: CARVIX Project Roadmap

## Metadata

- Status: APPROVED
- Related issue: N/A
- Owner: Team
- Reviewer: Team
- Branch: develop
- Created: 2026-09-24
- Last updated: 2026-09-24

## Objective

Provide the fixed high-level sequence for delivering the CARVIX MVP. Each implementation stage must receive its own detailed plan before coding.

## Approved Sequence

1. Configure the development environment and PostgreSQL.
2. Confirm or create the custom user model before the first production migration.
3. Implement authentication, profiles, and Owner, Technician, and Administrator roles.
4. Implement the core domain models.
5. Complete normal vehicle, maintenance, appointment, technician, and inventory workflows without AI.
6. Enforce and test ownership and RBAC.
7. Add the asynchronous chatbot interface with a controlled placeholder response.
8. Implement and test `check_required_maintenance` as a normal Django service.
9. Implement and test `list_available_service_slots` and confirmed atomic booking.
10. Connect registered tools to the external LLM.
11. Add seed data and complete automated tests.
12. Complete documentation and rehearse the demonstration.

## Enduring Constraints

- Keep the project within the approved MVP scope.
- Manual booking must work before AI booking.
- Django controls identity, permissions, validation, transactions, business rules, and logging.
- The LLM has no direct database access.
- Each stage requires a separate approved plan and pull request.

## Approval

- Decision: APPROVED
- Approved by: CARVIX Team
- Approval date: 2026-09-24
