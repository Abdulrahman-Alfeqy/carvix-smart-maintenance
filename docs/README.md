# CARVIX Documentation Sources

## Authoritative SRS

The only authoritative project requirements document is:

`docs/CARVIX_SRS_Group6.docx`

All implementation plans, model designs, migrations, tests, RBAC
decisions, user journeys, agent tools, and acceptance criteria must be
validated against this document.

## Supporting Documentation

The following files provide supporting diagrams and technical context.
They must not override the authoritative SRS:

- `docs/architecture.md`
- `docs/erd.md`
- `docs/user-journeys.md`
- Diagram images stored in `docs/`

If supporting documentation conflicts with
`docs/CARVIX_SRS_Group6.docx`, the DOCX SRS takes precedence.

## Obsolete Document

`docs/carvix-srs-v2.md` was an earlier draft and was removed to prevent
conflicting implementation decisions.

## Planning Rule

Before implementing a major feature:

1. Read the authoritative SRS.
2. Cite the relevant SRS sections in the task plan.
3. Record ambiguities as open questions.
4. Do not infer requirements from removed drafts or Git history.
5. Do not begin implementation while blocking questions remain.
