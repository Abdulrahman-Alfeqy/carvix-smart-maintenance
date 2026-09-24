# AI Workflow for CARVIX

This directory keeps implementation plans used by the two-person team and any AI assistant.

## Minimal setup

Only two permanent instruction files are required:

1. `/AGENTS.md`: shared project rules for humans and every AI.
2. `/.agents/PLAN_TEMPLATE.md`: template used to create a plan for each meaningful task.

The `.agents/plans/` directory contains one plan per GitHub issue or task.

## Using an AI that reads repository instructions

Tell it:

> Read `AGENTS.md`, then read the relevant approved plan in `.agents/plans/`. Follow both before changing the repository.

## Using an external chatbot

Upload or paste:

1. `AGENTS.md`
2. The relevant plan from `.agents/plans/`
3. Only the project files needed for the current task

Then use the prompt in `EXTERNAL_AI_PROMPT.md`.

## Team rule

One teammate owns implementation and the other reviews it. Do not have two AI agents independently implement the same task in parallel.
