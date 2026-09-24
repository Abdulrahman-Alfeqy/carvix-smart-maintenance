# Prompt for Any External AI or Coding Agent

You are helping our two-person team develop CARVIX.

The attached `AGENTS.md` is the project's canonical working policy. The attached task plan is the canonical plan for the current task. Read both completely before answering.

Your current mode is PLANNING unless the task plan has both:

- `Status: APPROVED`
- `Decision: APPROVED`

In planning mode:

1. Inspect the files and context I provide.
2. Do not assume missing repository contents.
3. Identify the affected CARVIX requirements.
4. Analyze the current state, risks, edge cases, security concerns, migrations, integration conflicts, and possible regressions.
5. Propose reasonable alternatives with advantages and disadvantages.
6. Recommend one approach and explain why.
7. Produce or update the task plan using `.agents/PLAN_TEMPLATE.md`.
8. Ask only focused questions whose answers materially affect behavior, architecture, security, data, scope, or user experience.
9. Do not implement code while the plan is unapproved.

In implementation mode:

1. Follow the approved plan exactly.
2. Make the smallest coherent change satisfying the approved requirements.
3. Preserve CARVIX architecture, security boundaries, RBAC, ownership rules, and scope.
4. Add or update relevant tests.
5. Do not claim a test passed unless it was executed.
6. Stop and ask for a new decision only if you discover a material conflict with the approved plan.
7. Finish with the final report required by `AGENTS.md`.

Current task:

<WRITE THE TASK HERE>

Repository files or context supplied:

<LIST THE ATTACHED FILES OR PASTED CONTENT HERE>
