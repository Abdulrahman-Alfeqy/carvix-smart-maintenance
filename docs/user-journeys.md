flowchart TD
    START(["User opens Carvix"]) --> AUTH{"Logged in?"}
    AUTH -- "Yes" --> DASH["Role-aware Dashboard"]
    AUTH -- "No" --> J0

    subgraph J0["Journey 0 - Register / Login"]
        L1["Open Register or Login page"] --> L2["Submit credentials"]
        L2 --> L3{"Valid credentials + account active?"}
        L3 -- "No" --> L4["Field errors / invalid credentials / deactivated account refused"] --> L1
        L3 -- "Yes" --> L5["Session created - redirect by role"]
    end

    J0 --> DASH
    DASH --> NEXT{"What next?"}
    ENDNODE(["End"])

    subgraph J1["Journey 1 - Add Vehicle (Client)"]
        V1["Open Vehicles page"] --> V2["Fill form: make, model, year, plate, VIN, mileage, fuel type"]
        V2 --> V3{"Server validation passed?"}
        V3 -- "No" --> V4["Field-level errors shown"] --> V2
        V3 -- "Yes" --> V5["Save via ORM to PostgreSQL"]
        V5 --> V6["Confirmation - vehicle appears in list"]
    end

    subgraph J2["Journey 2 - Manual Booking (Client)"]
        M1["Select own vehicle + maintenance type"] --> M2["System lists available ServiceSlots - any active technician may serve any type (FD-19)"]
        M2 --> M3{"Any slots?"}
        M3 -- "No" --> M4["Empty state - try another date range"] --> M2
        M3 -- "Yes" --> M5["Pick a slot"]
        M5 --> M6{"Transaction re-check: slot still free?"}
        M6 -- "No" --> M7["Error: slot just taken - refresh list"] --> M2
        M6 -- "Yes" --> M8["ServiceAppointment created - status PENDING"]
        M8 --> M9["Confirmation page with appointment number + notification"]
    end

    subgraph J3["Journey 3 - AI-Assisted Booking (Client)"]
        A1["Open chat - book a service for my car"] --> A2["Agent loads permitted context"]
        A2 --> A3["Tool: list_my_vehicles"]
        A3 --> A4{"More than one vehicle?"}
        A4 -- "Yes" --> A5["Agent asks which vehicle"] --> A6["Tool: check_maintenance_due"]
        A4 -- "No" --> A6
        A6 --> A7["Tool: get_available_slots"]
        A7 --> A8{"Slots available?"}
        A8 -- "No" --> A9["Agent suggests other dates"] --> A7
        A8 -- "Yes" --> A10["User taps a slot in chat UI"]
        A10 --> A11["Backend issues signed confirmation token - 5 min, single-use"]
        A11 --> A12{"User clicks Confirm?"}
        A12 -- "No" --> A13["No write performed - token expires"]
        A12 -- "Yes" --> A14["Tool: book_maintenance_appointment with token"]
        A14 --> A15{"Token valid + slot still free inside transaction?"}
        A15 -- "No" --> A16["Structured error - TOKEN_EXPIRED / SLOT_TAKEN"] --> A7
        A15 -- "Yes" --> A17["Appointment created + AuditLog entries + notification"]
        A17 --> A18["Agent confirms with appointment number, date, technician"]
    end

    subgraph J4["Journey 4 - Staff Lifecycle (Manager / Technician)"]
        S1["Manager creates technician slots - overlap rejected"] --> S2["Manager confirms appointment: PENDING to CONFIRMED"]
        S2 --> S3["Technician starts job: CONFIRMED to IN_PROGRESS"]
        S3 --> S4["Technician completes: MaintenanceRecord + PartUsage"]
        S4 --> S5{"Stock sufficient? (single transaction)"}
        S5 -- "No" --> S5F["INSUFFICIENT_STOCK - full rollback - NO notification sent"]
        S5 -- "Yes" --> S5OK["Stock decremented - status COMPLETED - transaction commits"]
        S5OK --> S5N["APPOINTMENT_COMPLETED notification sent to client - only after commit"]
        S5N --> S6["Client sees new maintenance history entry"]
    end

    subgraph J5["Journey 5 - Reschedule (Client / Manager) - FR-APT-06"]
        R1["Book NEW slot first (via J2 or J3)"] --> R1C{"New booking succeeded?"}
        R1C -- "No" --> R1F["SLOT_TAKEN / no slots - no write - pick another slot"] --> R1
        R1C -- "Yes" --> R2["Navigate to OLD active appointment"]
        R2 --> R3{"Cancel window >= 24h OR actor is Manager?"}
        R3 -- "Yes" --> R5["Cancel OLD appointment - second confirmation token"]
        R3 -- "No" --> R4["Client blocked by 24h rule - Manager must cancel on their behalf"]
        R4 --> R4M{"Manager approves cancellation?"}
        R4M -- "Yes" --> R5
        R4M -- "No" --> R4E["Old appointment remains active - user informed"]
        R5 --> R5C{"Old cancellation succeeded?"}
        R5C -- "No" --> R5F["Partial failure: BOTH appointments remain active - user clearly informed - Manager resolves the old one - no auto-rollback of the new booking"]
        R5C -- "Yes" --> R6["New appointment stays PENDING/CONFIRMED - reschedule done"]
    end

    subgraph J6["Journey 6 - Manual Historical Record (Manager) - FR-MNT-05"]
        H1["Manager opens vehicle profile"] --> H1A{"Actor is Manager/Admin AND vehicle active?"}
        H1A -- "No" --> H1F["403 / PERMISSION_DENIED - or controlled error: inactive vehicle"]
        H1A -- "Yes" --> H2["Selects Add Historical Record"]
        H2 --> H3["Fills form: maintenance type, past performed date, mileage, labor cost, notes - no slot/appointment"]
        H3 --> H4{"Valid? required fields present + past date + mileage >= 0 + labor >= 0"}
        H4 -- "No" --> H4F["Field errors shown"] --> H3
        H4 -- "Yes" --> H5["MaintenanceRecord saved with appointment_id = NULL"]
        H5 --> H6["Success message - record appears in vehicle history, visible to owner"]
    end

    NEXT --> J1
    NEXT --> J2
    NEXT --> J3
    NEXT --> J4
    NEXT --> J5
    NEXT --> J6

    V6 --> ENDNODE
    M9 --> ENDNODE
    A18 --> ENDNODE
    A13 --> ENDNODE
    S6 --> ENDNODE
    S5F --> ENDNODE
    R6 --> ENDNODE
    R4E --> ENDNODE
    R5F --> ENDNODE
    R1F --> ENDNODE
    H6 --> ENDNODE
    H1F --> ENDNODE
