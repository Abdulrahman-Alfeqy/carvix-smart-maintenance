flowchart TB
    subgraph BROWSER["CLIENT / BROWSER  (untrusted zone)"]
        UI["Django Templates - HTML5 + CSS3"]
        MAIN["main.js - CRUD pages"]
        CHAT["agent_chat.js - chat UI + slot picker + Confirm button"]
    end

    subgraph DJANGO["DJANGO MVT  (trusted zone - sole authority for authz, validation, writes)"]
        URLS["config/urls.py"]
        RBAC["RBAC Layer - login_required + RoleRequiredMixin + policy functions"]
        VIEWS["Views + Forms / Validation"]
        CHATEP["Chat Endpoint /agent/chat/ - rate limited 20 msg/min"]
        CTX["Context Builder - per-role, minimal, fresh per turn"]
        LOOP["Agent Loop - max 5 tool calls, LLM timeout 20s"]
        PROMPTS["prompts.py - System Persona + Guardrails"]
        DISP["Tool Dispatcher - role-aware allowlist of 13 registered tools - Admin inherits Manager set (FD-18) - role checked at dispatch AND inside domain service"]
        VAL["Schema Validator - JSON Schema (additionalProperties false) then Django Form / Pydantic"]
        AUTHZ["Authorization - request.user injected server-side + ownership checks"]
        CONF["Confirmation Token Verifier - signed, 5 min TTL, single-use, payload-bound"]
        SVC["Domain Services - services.py / selectors.py"]
        TX["Atomic Transaction + row locks + Django ORM"]
        AUDIT["Audit Logger - append-only AuditLog + correlation ID"]
    end

    DB[("PostgreSQL - carvix_db")]
    GEM["Google Gemini API - model gemini-flash-latest - function calling"]
    ENV["Server-side .env secrets - GEMINI_API_KEY, SECRET_KEY, DATABASE_URL"]

    MAIN -->|"fetch CRUD - HTTPS + session + CSRF"| URLS
    CHAT -->|"POST /agent/chat/ - HTTPS + CSRF"| URLS
    URLS --> RBAC
    RBAC --> VIEWS --> SVC
    RBAC --> CHATEP
    CHATEP --> CTX --> LOOP
    PROMPTS --> LOOP
    ENV -.->|"API key never reaches browser"| LOOP
    LOOP <-->|"prompt + context + role-scoped tool schemas  /  function_call JSON"| GEM
    LOOP -->|"structured tool_call only"| DISP
    DISP --> VAL --> AUTHZ
    AUTHZ -->|"write tools"| CONF
    AUTHZ -->|"read tools"| SVC
    CONF --> SVC
    SVC --> TX --> DB
    TX --> AUDIT
    SVC -->|"ToolResult envelope: success, error_code, message, data, correlation_id + Notification rows only when transaction commits"| LOOP
    LOOP -->|"final answer - never claims success without success = true"| CHAT
