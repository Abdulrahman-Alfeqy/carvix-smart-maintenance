# CARVIX Documentation Sources

## Authoritative SRS

The highest authority for CARVIX requirements is:

- [`CARVIX_SRS_Group6.docx`](CARVIX_SRS_Group6.docx)

All model designs, migrations, tests, RBAC decisions, agent Tools, and
acceptance criteria must be validated against this document.

## Final Approved Diagrams

The final approved design diagrams are:

- [`system architecture.jpeg`](system%20architecture.jpeg)
- [`ERD.jpeg`](ERD.jpeg)
- [`Workflow diagram.jpeg`](Workflow%20diagram.jpeg)

## Delivery Documents

The current delivery documents are:

- [`demo-runbook.md`](demo-runbook.md)
- [`demo-seed-data.md`](demo-seed-data.md)
- [`final-traceability.md`](final-traceability.md)

The project root [`README.md`](../README.md) contains setup, PostgreSQL,
migration, testing, Gemini configuration, and server-startup instructions.

## Removed Historical Drafts

Earlier Markdown diagram drafts were removed because they conflicted with
the authoritative SRS, the final approved diagrams, and the current
repository implementation. They included superseded role names, tool
counts, agent-round limits, and speculative schema elements.

Do not use removed drafts, Git history, or unofficial notes to introduce
requirements, roles, entities, fields, Tools, or workflows that are absent
from `CARVIX_SRS_Group6.docx` and the current repository.

Where any remaining material conflicts with the DOCX SRS, the DOCX SRS
takes precedence.

## Planning Rule

Before implementing a major feature:

1. Read the authoritative SRS.
2. Cite the relevant SRS sections in the task plan.
3. Record ambiguities as open questions.
4. Do not infer requirements from removed drafts or Git history.
5. Do not begin implementation while blocking questions remain.
