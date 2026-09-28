# CARVIX Final SRS Traceability

This concise map supports final review of CARVIX MVP behavior. The authoritative requirements are in [`CARVIX_SRS_Group6.docx`](CARVIX_SRS_Group6.docx); supporting architecture, ERD, and journey documents do not override it. Implementation evidence points to current Django code and automated tests. Exact validation results for the final audit are recorded in [Plan 020](../.agents/plans/020-final-audit-delivery.md).

## Functional requirements

| SRS requirement | Implemented workflow / status | Primary code | Validation evidence |
| --- | --- | --- | --- |
| FR-01–04 | Public registration creates an Owner; login/logout and own-profile access use Django sessions; role and privileged flags are not registration/profile fields. | `apps/authentication/forms.py`, `views.py`, `models.py` | `apps.authentication.tests` |
| FR-05–07 | Owner creates and updates only owned vehicles; ownership is server-bound, mutable fields are allowlisted, plate uniqueness and mileage are validated. | `apps/vehicles/views.py`, `forms.py`, `models.py` | `apps.vehicles.tests` |
| FR-08, FR-11 | Owner vehicle detail shows owner-scoped history and maintenance due status calculated from intervals and records. | `apps/vehicles/views.py`, `apps/maintenance/services.py` | `apps.vehicles.tests`, `apps.maintenance.tests`, `apps.ai_agent.test_read_tools` |
| FR-09 | ServiceType and intervals are manageable through authorized Django Admin model permissions. | `apps/maintenance/admin.py`, `apps/maintenance/models.py` | `apps.maintenance.tests`; Django Admin workflow is permission-gated by Django |
| FR-10, FR-16–17, FR-20 | Technician sees assigned appointments, starts service, completes only in-progress work, records MaintenanceRecord/parts, and reduces stock atomically. | `apps/appointments/views.py`, `services.py`, `forms.py`; `apps/maintenance/models.py` | `apps.appointments.tests`, `apps.maintenance.tests`, `apps.inventory.tests` |
| FR-12–14 | Owner manual booking form lists active future slots with capacity; booking rechecks slot state/capacity/duplicates transactionally. | `apps/appointments/forms.py`, `selectors.py`, `services.py` | `apps.appointments.tests` including PostgreSQL concurrency/constraints |
| FR-15 | Owner appointment list/detail are implemented. Cancellation is **deferred**: FR-15 is Should and the SRS does not define eligible statuses and cancellation semantics sufficiently for a safe implementation. | `apps/appointments/views.py`; no cancellation endpoint | No cancellation claim; deferred scope |
| FR-18 | Domain Administrator assigns a valid available Technician to an unassigned appointment. | `apps/appointments/views.py`, `forms.py`, `services.py` | `apps.appointments.tests` |
| FR-19 | SparePart records and quantities are manageable through authorized Django Admin; Technician completion reduces stock without permitting a negative quantity. | `apps/inventory/admin.py`, `models.py`; `apps/appointments/services.py` | `apps.inventory.tests`, `apps.appointments.tests` |
| FR-21–22 | Authenticated asynchronous Chat uses role-appropriate server-built JSON context; the Provider receives no ORM objects or client-selected identity. | `apps/ai_agent/views.py`, `context.py`, `static/js/agent_chat.js` | `apps.ai_agent.tests`, `apps.ai_agent.test_tool_integration`, `apps.ai_agent.test_live_provider` |
| FR-23 | Owner maintenance Tool scopes the Vehicle to the actor and reuses due-service logic. | `apps/ai_agent/maintenance_tool.py`, `apps/maintenance/services.py` | `apps.ai_agent.test_read_tools`, `apps.ai_agent.test_tool_integration` |
| FR-24 | Slot Tool reuses the global active/future/capacity selector. Configured service IDs/names are included in safe Provider context. `preferred_date` is validated but does not filter, and slots are not service-specific because no relation exists. | `apps/ai_agent/slot_tool.py`, `context.py`, `apps/appointments/selectors.py` | `apps.ai_agent.test_read_tools`, `apps.ai_agent.test_tool_integration` |
| FR-25–30 | AI booking requires exact explicit confirmation, uses the authenticated actor, reuses the transactional booking service, and sets `booked_by_agent=True` server-side. | `apps/ai_agent/booking_tool.py`, `apps/appointments/services.py` | `apps.ai_agent.test_booking_tool`, `apps.ai_agent.test_tool_integration`, `apps.appointments.tests` |
| FR-31–32 | Each executed registered Tool has one sanitized AgentActionLog and returns the five-field structured result. Success booking and SUCCESS audit commit atomically. Unknown Tools do not execute. | `apps/ai_agent/tools.py`, `models.py`, `sanitization.py` | `apps.ai_agent.test_booking_tool`, `apps.ai_agent.tests`, `apps.ai_agent.test_tool_integration` |
| FR-33 | Agent responses preserve backend success/failure; Provider text cannot override failure or claim an unverified booking. | `apps/ai_agent/agent.py`, `prompts.py` | `apps.ai_agent.test_tool_integration`, `apps.ai_agent.test_live_provider` |
| FR-34 | Invalid Chat input and unavailable/malformed Provider responses return safe errors; missing Gemini credentials do not disable manual workflows. | `apps/ai_agent/views.py`, `agent.py`, `provider.py`, `live_provider.py` | `apps.ai_agent.tests`, `apps.ai_agent.test_live_provider` |
| FR-35 | AgentActionLog inspection is view-only and requires Django Admin permission plus domain ADMINISTRATOR role. | `apps/ai_agent/admin.py`, `models.py` | `apps.ai_agent.tests` |

## Non-functional requirements

| SRS requirement | Implementation evidence | Validation evidence / limit |
| --- | --- | --- |
| NFR-P01 | Normal Django pages have no Provider dependency. | Five repeated in-process `GET /vehicles/` requests with seeded PostgreSQL test data had a maximum of 0.005s and median of 0.004s in the Django test client. This is a local test-client measurement, not a production/network load benchmark. |
| NFR-P02 | Selectors and maintenance overview use bounded joined/aggregate query patterns where appropriate. | Query-count assertions in `apps.appointments.tests`, `apps.maintenance.tests`, and `apps.vehicles.tests`. |
| NFR-S01–04 | Login gates, role checks, owner-scoped and assigned-scoped querysets, and backend authorization protect private routes. | Anonymous, wrong-role, IDOR, assignment, and forged-field coverage in authentication, vehicles, appointments, and AI Agent tests. |
| NFR-S05–07 | Provider schemas exclude identity; Django binds request.user; no raw SQL path; examples are placeholders; tool/provider failures are sanitized. | Provider, tool, sanitizer, secret-scan and response tests; final audit does not print matched secret values. |
| NFR-U01–03 | Responsive stylesheet, accessible Chat status, asynchronous feedback, and text-only rendering are present. | Template, JavaScript, and responsive CSS inspection plus Chat behavior tests. Browser login view checked at 390px and 1440px; document width matched each viewport. Other authenticated pages remain on the manual demo screenshot checklist. |
| NFR-R01–03 | Booking and completion transactions, locks, rollback, audit records, and Provider failure boundaries are implemented. | PostgreSQL booking/completion concurrency, rollback, Tool audit and Provider failure tests. |
| NFR-D01–04 | Database/model/form checks keep mileage, stock, slot capacity/time ranges, statuses, and foreign-key history valid. | PostgreSQL constraint and workflow tests across vehicles, appointments, maintenance, inventory, and AI Agent. |
| NFR-M01–02 | Django app boundaries separate authentication, vehicles, maintenance, appointments, inventory, and AI Agent; business rules live in services/selectors. | Code review, Django system check, migration check, and application suites. |

## Deferred or limited behavior

- Owner cancellation remains deferred (FR-15 Should; cancellation eligibility/transition rules are undefined).
- Chat history is request-local and not persisted.
- The available-slot Tool validates `preferred_date` but does not filter by it. Slot availability is global because the accepted model has no ServiceType-to-ServiceSlot relationship.
- Live Gemini smoke testing is optional and is performed only when a key is configured; automated Provider tests use mocks. The final audit does not perform a live booking.
- Payments, maps/GPS, mobile or voice applications, WebSockets, RAG, embeddings, vector databases, multiple agents, predictive ML, multiple branches, and supplier/financial systems are outside the approved MVP.
