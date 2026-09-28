# Plan 019: Live LLM Provider Integration and Delivery Readiness

## Metadata

- Status: IMPLEMENTED
- Related issue: N/A
- Owner: Abdalrahaman Atef
- Reviewer: Abdalrahaman Atef
- Branch: feature/live-provider-integration
- Created: 2026-09-28
- Last updated: 2026-09-28

## Objective

Connect the existing Plan 014 Provider boundary and Plan 018 bounded Agent loop to the Gemini Developer API using Google's supported Python SDK. Translate approved internal Tool schemas and sanitized observations to Gemini's function-calling format, convert only one valid Gemini response into `ProviderReply`, keep every Tool execution in the existing Agent and Django Registry, and preserve safe behavior when Gemini is unavailable.

## Requirements Covered

Authoritative evidence: `docs/CARVIX_SRS_Group6.docx`, approved Version 1.0.

- §5.1 names the External LLM API as Google Gemini with `gemini-flash-latest` and function calling.
- §5.2 requires minimum context, environment-stored sensitive configuration, and structured observations returned to the LLM.
- §§8.1–8.6 and FR-21–34 require role-safe context, approved Tools, server-owned identity, validation/authorization in Django, explicit confirmation, transactional booking, structured results, truthful outcomes, and safe Provider failure.
- NFR-S05–S07 and NFR-R02 require no model-supplied identity/raw SQL, sanitized errors, and no data corruption when LLM/network calls fail.
- Plan 018 remains authoritative for the exact three Tool names, internal schemas, role-filtered exposure, three Tool rounds, repeated-call prevention, AgentActionLog transactions, backend-truth behavior, and no Models/Migrations.

The supporting `docs/architecture.md` also names Gemini but contains historical details that conflict with the SRS and Plan 018 (including 13 Tools, five rounds, and other unimplemented components). The SRS and completed Plan 018 control this implementation; no historical architecture redesign is included.

## Current-State Analysis

- Baseline: clean branch `feature/live-provider-integration`, `HEAD dd1001035051f858815225200ae99a46bd4eb7f5`, the expected PR #24 / Plan 018 merge commit. Local `main` and the cached `origin/main` ref point to the same commit. A network fetch could not update refs because `.git/FETCH_HEAD` is read-only in this workspace.
- `apps/ai_agent/provider.py` defines the stable `ProviderReply(text, tool_call)` contract and `UnavailableProvider`; no SDK or live adapter exists.
- `agent.py` keeps a request-local three-round loop, exposes role-filtered schemas and observations in JSON-native context, dispatches only through the central Registry, and preserves backend/audit truth. Its parser currently accepts a `ProviderReply` containing both text and a Tool call; the live adapter will reject ambiguous mixed Gemini output and a narrow Agent parser check will keep the abstraction strict for every Provider.
- `tool_schemas.py` defines exactly the three approved contracts with `additionalProperties: false`; `tools.py` registers their existing validated Django Handlers and owns exactly-once audit and booking/audit atomicity.
- `requirements.txt` pins direct dependencies. Neither `google.genai` nor `google.generativeai` is installed in `.venv`; no alternative Provider SDK is present.
- `config/settings.py` loads `.env` through python-dotenv and reads other configuration from environment variables. PostgreSQL is the only configured database.
- `docs/CARVIX_SRS_Group6.docx` explicitly settles Provider choice and model alias, so no Provider decision blocker remains.
- Initial `pg_isready` failed. `sudo -n systemctl start postgresql` was attempted as directed but the container's no-new-privileges restriction prevented sudo; a second `pg_isready` also failed. PostgreSQL test validation is therefore an environment gate and must remain reported as not run if the service cannot be made available.

## Provider and Dependency Decision

- Provider: Google Gemini Developer API, not Vertex/Enterprise Agent Platform.
- Model: environment setting `GEMINI_MODEL`, default `gemini-flash-latest`, as named by authoritative SRS §5.1. The value is configurable; do not silently substitute another model.
- SDK: add only the official `google-genai==2.25.0` package. It is absent locally, supports Python 3.12, is Google’s currently documented Python SDK, and the repository pins dependencies exactly. Do not add the deprecated `google-generativeai` package or optional SDK extras.
- Official SDK evidence: [Google Gemini API libraries](https://ai.google.dev/gemini-api/docs/libraries), [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/), [function calling](https://ai.google.dev/gemini-api/docs/function-calling), and [official SDK release v2.25.0](https://github.com/googleapis/python-genai/releases/tag/v2.25.0). SDK documentation specifies function declarations/function responses, `HttpOptions.timeout`, and a default of five retry attempts; configure one attempt so the SDK performs no automatic retry.

## Environment Contract

- `GEMINI_API_KEY`: optional local/deployment secret; absent or blank disables AI with existing `provider_unavailable` behavior. Read only on the server. No key is stored in source, tests, prompts, logs, Chat output, AgentActionLog, screenshots, or examples.
- `GEMINI_MODEL`: defaults to the authoritative SRS value `gemini-flash-latest`; nonblank environment value selects a configured Gemini model.
- `GEMINI_TIMEOUT_SECONDS`: defaults to `20`; accept only integer values from `1` through `30`. Twenty seconds follows the supporting architecture's bounded-call setting without adopting its conflicting tool/loop design. Missing/invalid bounds produce safe Provider-unavailable behavior and do not prevent non-AI pages from loading.
- No separate enabled flag is required: a missing key is the off switch.
- Add placeholders only to `.env.example`; document setup in README. Do not edit the demo runbook unless a necessary narrow setup instruction cannot fit in README.

## Provider Adapter Contract

Preserve `Provider.generate(*, message, system_prompt, context) -> ProviderReply`; the adapter has no Model/domain imports, ORM access, transaction, Tool handler, Actor argument, or audit responsibility. The Agent creates a request-local adapter; the adapter keeps only in-memory Gemini conversation contents and the pending function-call name/ID for that one Agent turn.

- Use synchronous `genai.Client(api_key=..., http_options=HttpOptions(timeout=seconds*1000, retry_options=HttpRetryOptions(attempts=1)))` and the official `models.generate_content` API.
- Send `system_prompt` as Gemini system instruction. Send the user message and JSON-native application context as a user Content; omit the reserved schema/observation entries from this context body because schemas are sent as declarations and observations are sent as function responses.
- Send only role-filtered internal schemas from the current Agent context. Convert each exact approved internal schema to a Gemini `FunctionDeclaration`/`Tool`; pass declarations only, never Python callables. The declarations themselves contain only the exposed names; use AUTO function selection while disabling automatic function execution. Any unexpected function name is refused by the Agent Registry before dispatch.
- Project parameters to Gemini's documented Function Calling schema subset: retain the object shape, field names, base types, descriptions, and required fields; map the internal positive-ID integer/string `oneOf` to the documented integer Provider shape; omit internal `minimum`, `format`, `pattern`, and `additionalProperties` keywords that are not part of the documented subset. The exact internal schema is verified before projection, and the existing Django Handlers remain authoritative for positivity, date formats, and rejection of extra arguments.
- Keep the candidate's original model Content (including provider metadata required for the next turn) in memory. When the Agent supplies a new observation, append a Gemini `role="tool"` function response using the exact Tool name and only the five internal result fields `success`, `code`, `message`, `data`, `errors`. No Actor, SDK result object, ORM object, QuerySet, exception, SQL, database detail, or secret is included.
- Limit conversion to one final text part or one function-call part. Require a nonblank string for text, a nonempty Tool name, and dictionary/JSON-native arguments. Reject no candidate, multiple candidates/parts/function calls, missing name/arguments, non-object arguments, mixed text plus Tool call, unexpected response/part shapes, and non-`STOP` finish reasons. Unknown function names may become a safe internal `ProviderReply`; the existing Agent refuses them before dispatch.
- Do not return SDK response, Candidate, Content, Part, FunctionCall, or exception instances beyond the adapter. Preserve the exact `ProviderReply` dataclass shape.
- A narrow backward-compatible `agent.py` parser guard rejects mixed internal text plus Tool-call replies. No loop, Tool, registry, response JSON, or transaction behavior changes.

## Provider Failure Mapping and Retry Policy

- Missing/blank API key, invalid timeout configuration, SDK import/client errors, authentication rejection, rate limiting, timeout, and network/service failures raise `ProviderUnavailable` without retaining or exposing provider exception text. These map to the existing stable Chat code `provider_unavailable` and HTTP 503.
- Empty, malformed, unsupported-finish, mixed, multiple-call, or otherwise unexpected SDK responses raise an internal response error with no provider details; the existing Agent maps it to safe `provider_error` / HTTP 502.
- The SDK HTTP client uses one attempt (`attempts=1`), so it does not automatically retry. Each Provider generation can return at most one Tool request; the existing Agent loop remains bounded at three dispatched Tools and owns duplicate/booking-repeat prevention.
- Provider calls stay before/after completed dispatcher transactions. The live adapter never starts or extends a database transaction. If a final generation fails after a successful booking, Plan 018 returns the committed booking truth; a failed Tool remains a failure.

## Alternatives Considered

### Option A — Official Gemini SDK behind the current Provider seam (Recommended)

Use the required Gemini Developer API and current official SDK; translate schemas, request/reply content, and observations only in one new adapter. Advantages: matches explicit SRS, keeps Django the sole execution authority, and preserves Fake Provider compatibility. Disadvantages: adds a direct dependency and requires an optional API key for live verification.

### Option B — Keep `UnavailableProvider` or use a REST call through the standard library

Keeping the stub does not meet SRS §5.1. A hand-built REST client avoids an SDK dependency but duplicates Google's authentication, schema, response, timeout, and error handling and is not the official supported integration. Both are rejected.

## Recommended Approach

Choose Option A. Implement one request-local `GeminiProvider` adapter in `apps/ai_agent/live_provider.py`, select it only when a nonblank key exists, and preserve the existing Agent, central Registry, handlers, and manual workflows. The only Agent change is rejection of ambiguous mixed `ProviderReply` values. Mock the SDK boundary in every automated test; do not require network access for tests.

## Expected Files and Implementation Order

1. `.agents/plans/019-live-provider-integration.md`: approved design and final validation report.
2. `requirements.txt`: add only `google-genai==2.25.0`.
3. `config/settings.py` and `.env.example`: add environment-only Gemini key/model/timeout settings and placeholders.
4. `apps/ai_agent/provider.py`: preserve reply protocol; select the live adapter only when configured, otherwise preserve `provider_unavailable`.
5. `apps/ai_agent/live_provider.py`: implement schema conversion, bounded SDK request, in-memory Tool conversation, strict reply parsing, observation conversion, and safe exception containment.
6. `apps/ai_agent/agent.py`: reject mixed text/Tool internal replies without changing the 3-round loop.
7. `apps/ai_agent/test_live_provider.py`: mock the official SDK boundary and cover configuration, text/tool conversion, observations, failures, timeouts/retries, and no-network behavior.
8. `README.md`: add Gemini setup and safe missing-key behavior.
9. `apps/ai_agent/tests.py`: patch the existing provider-unavailable view test so it remains offline even when `GEMINI_API_KEY` is configured. This narrow test isolation change is necessary because the default provider now selects Gemini when configured; it does not change production behavior or expand the feature scope.

No other file is expected. No Handler, service, selector, model, migration, template, frontend, URL, prompt, SRS, or demo-runbook change is planned.

## Automated Test Strategy

Every test replaces the official SDK client/call boundary with a fake or mock; no test performs a real network request.

- Configuration: missing/blank key, configured key/model, authoritative model default, invalid and bounded timeout, no key/config value in repr/log/Chat output.
- Text: valid final text; empty response/candidates; blank text; malformed typed response; wrong/missing candidate; unexpected finish reason; SDK object cannot escape.
- Schemas and requests: each of the exact three internal contracts converts to Gemini's documented schema subset; compare exposed field names, base types, descriptions, and required/optional fields with the internal contracts. Verify the internal contracts still reject additional properties and retain server-side constraints; no identity/server-owned fields, role-filtered schema set, one candidate, automatic execution disabled, timeout milliseconds, retries set to one. Gemini documents that Function Calling accepts only a subset of OpenAPI: [Function calling with the Gemini API](https://ai.google.dev/gemini-api/docs/function-calling).
- Tool responses: each of the three approved Tool names returns a single `ProviderReply` with JSON-native dictionary args; missing name/args, non-object args, multiple calls, mixed text/call, malformed SDK part, and unsupported finish reason are refused. Unknown name reaches Agent refusal without dispatch.
- Observation round trip: success for maintenance/slots/booking and a failed Tool each become one exact-name `FunctionResponse` with only `success`, `code`, `message`, `data`, `errors`; final text converts back into the existing reply contract.
- Failures: missing credentials, mocked timeout, 429/rate limit, 401/403 credentials, network exception, client-construction exception, malformed response, and internal parser failure yield only stable safe codes/messages with no exception text/key.
- Side-effect safety: a repeated Gemini call is still handled by Plan 018 guards; no SDK callable runs a Tool; at most one proposed call per response; Agent retains max three dispatches, backend failure truth, and successful-booking fallback if final generation fails; API calls occur outside dispatcher transactions.
- Compatibility: existing Fake Provider and Chat result contracts remain valid; exact three registry tools remain; no Provider configuration leaves manual routes usable and Chat safely unavailable. Every view test that invokes the Agent patches its Provider boundary so the suite cannot make a real network call when an API key is present.

## Migration and Environment Impact

`MIGRATIONS_EXPECTED: NO`. No Models or Migrations change. The only new runtime dependency is `google-genai==2.25.0`. Optional server environment variables are `GEMINI_API_KEY`, `GEMINI_MODEL`, and `GEMINI_TIMEOUT_SECONDS`; `.env.example` contains placeholders only. Rollback removes the adapter/dependency/settings/example/docs changes and restores `UnavailableProvider`; manual workflows and the central Tool contracts remain intact.

## Security and Risk Analysis

- API key exists only in process/environment configuration and the SDK client constructor. Never include it in content, schemas, exceptions, logs, AgentActionLog, or Chat.
- Only minimal JSON-native safe context and role-filtered approved declarations are sent to Gemini. The internal schema excludes actor identity; `request.user` is passed only inside Django after the Provider reply.
- The SDK receives no Python callable, ORM/model code, database credentials, QuerySet, or transaction handle. Tool calls pass through the strict existing parser, exact Registry, central validation, ownership checks, and audit boundary.
- Gemini output is untrusted. Strict typed response parsing rejects ambiguous/malformed/multiple/unsupported outputs; unknown names are refused by the Agent; backend results remain authoritative.
- SDK default retry behavior is five attempts according to the official SDK reference; configure attempts to one. Tool execution remains outside SDK/client behavior and cannot be repeated by transport retries.
- Timeouts are 20 seconds by default and 1–30 seconds by configuration. No key means no SDK client is created and all non-AI pages keep working.
- Live smoke test is at most one direct text generation or read-only Tool. Never use booking for first smoke test. If no key exists, mark it NOT RUN and complete mocked/static checks.
- The baseline supporting architecture/ERD include historical content. SRS and Plans 013–018 control; no stale Tool count, role, model, persistence, or architecture is reintroduced.

## Test Plan and Validation Gates

1. Check actual branch, clean status, baseline HEAD, and three registered Tool/schema names.
2. Check PostgreSQL with `pg_isready`; if unavailable, attempt `sudo -n systemctl start postgresql`, then recheck. If still unavailable, continue static review only; do not stage, commit, push, or mark IMPLEMENTED.
3. Run `.venv/bin/python manage.py check`.
4. Run `.venv/bin/python manage.py makemigrations --check` and inspect Models/Migrations.
5. Run exact focused `apps.ai_agent.test_live_provider` tests.
6. Run Plan 018 `apps.ai_agent.test_tool_integration` tests.
7. Run all `apps.ai_agent` tests.
8. Run relevant `appointments`, `authentication`, `vehicles`, and `maintenance` tests.
9. Run Demo Seed Data tests.
10. Run the complete PostgreSQL suite.
11. Run `git diff --check`, inspect environment/secret status without printing values, and review the complete diff/boundaries.
12. Perform one independent read-only review for BLOCKER, HIGH, MEDIUM across the 23 stated Provider, schema, boundary, safety, retry, secret, and compatibility requirements.

Stop at the first real test/implementation failure. Classify it before making the smallest correction. If any production source is corrected, rerun focused tests, all AI Agent tests, and the full PostgreSQL suite.

## Definition of Done

- Focused Provider tests, Plan 018 integration tests, all AI Agent tests, relevant domain tests, Demo Seed Data tests, and the complete PostgreSQL suite pass.
- Django and migration checks pass; no Model or Migration changes exist.
- The changed-file/secret scan and complete diff review are clean, with no BLOCKER, HIGH, or MEDIUM review finding.
- Live smoke-test status is recorded accurately; automated tests use only a mocked SDK boundary.
- Plan status is `IMPLEMENTED` only after all validation gates pass. A missing PostgreSQL service blocks that transition and Git delivery.

## Open Questions

None blocking. The authoritative SRS explicitly selects Gemini and the model alias; current project contracts settle all Tool and Agent-loop behavior.

## Approval

- Decision: APPROVED
- Approved by: Abdalrahaman Atef
- Approval date: 2026-09-28

## Implementation Report

- Summary: Implemented the optional Gemini adapter, environment-backed configuration, setup documentation, schema projection, strict response handling, and mocked SDK-boundary tests. PostgreSQL, dependency, regression, migration, and whitespace validation gates passed using the manually supplied results recorded below.
- Files created: `apps/ai_agent/live_provider.py`; `apps/ai_agent/test_live_provider.py`.
- Files modified: `.env.example`; `README.md`; `apps/ai_agent/agent.py`; `apps/ai_agent/provider.py`; `apps/ai_agent/tests.py`; `config/settings.py`; `requirements.txt`.
- Environment contract: `GEMINI_API_KEY` is optional; `GEMINI_MODEL` defaults to `gemini-flash-latest`; `GEMINI_TIMEOUT_SECONDS` defaults to 20 and accepts 1–30. No key was found in the process environment or local `.env`; values were not printed. `.env` is ignored and untracked.
- SDK/dependency: Added the official `google-genai==2.25.0` dependency. The repository-local `.venv` installation was manually verified with `python -m pip show google-genai`; reported version: 2.25.0.
- Provider request/schema/reply/observation conversion: Only exact, role-filtered internal schemas become Gemini function declarations, projected to the documented schema subset while preserving fields, base types, descriptions, and requiredness; Django Handlers retain all value and extra-field validation. No callable references are sent. The adapter accepts one final text part or one function-call part and converts it to the unchanged `ProviderReply` shape. It preserves the model call content in request-local memory and returns a matching `role="tool"` function response containing exactly `success`, `code`, `message`, `data`, and `errors`.
- Timeout and retry behavior: SDK HTTP timeout is `GEMINI_TIMEOUT_SECONDS * 1000` milliseconds; SDK retry attempts are explicitly set to 1. Both are verified by mocked tests.
- Provider failure mapping: Missing key, invalid timeout, import/client/request failures map to safe `provider_unavailable`; malformed or unsupported responses map through the Agent to safe `provider_error`. Raw SDK exception text is discarded.
- Secret handling: Changed-file scan found no Google API key, token, bearer credential, or credential-bearing URL pattern; matched values are never emitted. `.env` is not tracked or staged.
- Tests executed and exact results: User-supplied manual validation reports focused Plan 019 tests 19/19 passed; Plan 018 tool-integration tests 18/18 passed; all AI Agent tests 109/109 passed; Appointments, Authentication, Vehicles, and Maintenance tests 222/222 passed; Demo Seed Data tests 4/4 passed; complete PostgreSQL suite 338/338 passed. Every command completed with `OK`. Django check passed; `.venv/bin/python manage.py makemigrations --check` reported no changes; `git diff --check` passed. Tests were not rerun during this finalization turn, per instruction.
- Live smoke test (PASSED / FAILED / NOT RUN): NOT RUN. No real API key was available; the SDK was installed and verified locally, and no live Gemini request was made.
- PostgreSQL availability and validation: User reports PostgreSQL accepted connections throughout validation and all PostgreSQL-dependent suites passed, including the 338/338 full suite.
- Django check / migration check / whitespace: Django check passed; migration check reported no changes; whitespace check passed.
- Model/Migration verdict: No Models or Migrations changed; `MIGRATIONS_EXPECTED: NO` remains satisfied.
- Independent-style review verdict and findings: Complete changed-file and diff review found no BLOCKER, HIGH, or MEDIUM issue across the requested Provider, schema, boundary, security, transaction, retry, and compatibility checks. Review did not call Gemini or another external API.
- Commit/push: Authorized final delivery step for this Plan 019 implementation; the task report records the resulting commit and push state.
- Remaining risks/deferred scope: Live Gemini smoke test remains NOT RUN because no key was available. Persistent Chat history, Owner cancellation, and all other previously deferred scope remain deferred.
- Deviations from plan: Added a narrow patch to `apps/ai_agent/tests.py` after discovery showed its Provider-unavailable view test would otherwise invoke the configured live Provider. This makes that test remain offline and changes no production behavior. The optional SDK `allowed_function_names` field is omitted; only approved role-filtered declarations are sent, and the Agent Registry rejects any unexpected name.
