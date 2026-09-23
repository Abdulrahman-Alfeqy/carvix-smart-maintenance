erDiagram
    USER ||--o{ VEHICLE : "owns (CASCADE)"
    USER ||--o{ SERVICE_SLOT : "works as technician (PROTECT)"
    USER ||--o{ SERVICE_APPOINTMENT : "creates as created_by (PROTECT)"
    USER ||--o{ MAINTENANCE_RECORD : "performs as technician (SET_NULL)"
    USER ||--o{ CHAT_SESSION : "has (CASCADE)"
    USER ||--o{ AUDIT_LOG : "triggers (SET_NULL)"
    USER ||--o{ NOTIFICATION : "receives (CASCADE)"

    VEHICLE ||--o{ SERVICE_APPOINTMENT : "booked for (PROTECT)"
    VEHICLE ||--o{ MAINTENANCE_RECORD : "serviced in (PROTECT)"

    MAINTENANCE_TYPE ||--o{ SERVICE_APPOINTMENT : "categorizes (PROTECT)"
    MAINTENANCE_TYPE ||--o{ MAINTENANCE_RECORD : "categorizes (PROTECT)"

    SERVICE_SLOT ||--o{ SERVICE_APPOINTMENT : "reserved by - max 1 active (PROTECT)"
    SERVICE_APPOINTMENT ||--o| MAINTENANCE_RECORD : "produces 1:1 nullable (SET_NULL)"

    MAINTENANCE_RECORD ||--o{ PART_USAGE : "consumes (PROTECT)"
    SPARE_PART ||--o{ PART_USAGE : "used in (PROTECT)"

    CHAT_SESSION ||--o{ CHAT_MESSAGE : "contains (CASCADE)"
    CHAT_SESSION ||--o{ AUDIT_LOG : "has (SET_NULL)"

    USER {
        bigint id PK
        string username "unique"
        string email "unique"
        string password_hash
        string role "CLIENT | TECHNICIAN | MANAGER | ADMIN"
        string phone
        string avatar
        boolean is_active
        datetime created_at
    }

    VEHICLE {
        bigint id PK
        bigint owner_id FK "NOT NULL, CASCADE"
        string make
        string model
        integer year "check 1950..current+1"
        string license_plate "unique"
        string vin "unique, nullable"
        integer mileage "check >= 0, never decreases for clients"
        string fuel_type "PETROL | DIESEL | ELECTRIC | HYBRID"
        boolean is_active
        datetime created_at
        datetime updated_at
    }

    MAINTENANCE_TYPE {
        bigint id PK
        string name "unique"
        text description
        integer interval_km "default 10000"
        integer interval_days "default 180"
        decimal base_cost "check >= 0"
        boolean is_active
        datetime created_at
    }

    SERVICE_SLOT {
        bigint id PK
        bigint technician_id FK "role must be TECHNICIAN, PROTECT"
        datetime starts_at
        datetime ends_at "check ends_at > starts_at"
        boolean is_active
        datetime created_at
    }

    SERVICE_APPOINTMENT {
        bigint id PK
        bigint created_by_id FK "actor who booked, PROTECT"
        bigint vehicle_id FK "owner derived via vehicle, PROTECT"
        bigint maintenance_type_id FK "PROTECT"
        bigint slot_id FK "PROTECT, partial unique: 1 active booking per slot"
        string status "PENDING | CONFIRMED | IN_PROGRESS | COMPLETED | CANCELLED"
        text notes
        datetime created_at
        datetime updated_at
    }

    MAINTENANCE_RECORD {
        bigint id PK
        bigint vehicle_id FK "PROTECT"
        bigint maintenance_type_id FK "PROTECT"
        bigint appointment_id FK "unique, nullable 1:1, SET_NULL - documented exception (FD-17)"
        bigint technician_id FK "performer, nullable, SET_NULL - documented exception (FD-17)"
        datetime performed_at "not in future"
        integer mileage_at_service "check >= 0"
        decimal labor_cost "check >= 0"
        text notes
        datetime created_at
    }

    SPARE_PART {
        bigint id PK
        string name
        string part_number "unique"
        decimal unit_price "check >= 0"
        integer stock_quantity "check >= 0"
        integer reorder_level "default 5"
        datetime created_at
    }

    PART_USAGE {
        bigint id PK
        bigint maintenance_record_id FK "PROTECT"
        bigint spare_part_id FK "PROTECT"
        integer quantity "check > 0"
        decimal unit_price "historical snapshot"
    }

    NOTIFICATION {
        bigint id PK
        bigint user_id FK "recipient, NOT NULL, CASCADE"
        string type "APPOINTMENT_BOOKED | APPOINTMENT_CONFIRMED | APPOINTMENT_COMPLETED | APPOINTMENT_CANCELLED | JOB_ASSIGNED | LOW_STOCK"
        string title
        text body
        string link "nullable, in-app URL"
        boolean is_read "default false"
        datetime created_at "committed only with triggering transaction (FR-NOT-01)"
    }

    CHAT_SESSION {
        bigint id PK
        bigint user_id FK "CASCADE - owned non-historical data; retention via soft delete only (FR-AUTH-06)"
        string title
        datetime created_at
        datetime updated_at
    }

    CHAT_MESSAGE {
        bigint id PK
        bigint session_id FK "CASCADE"
        string role "user | assistant | tool | system"
        text content
        string tool_name
        jsonb tool_payload "max 16KB"
        jsonb tool_result "max 16KB"
        jsonb context
        datetime created_at
    }

    AUDIT_LOG {
        bigint id PK
        bigint user_id FK "nullable, SET_NULL - actor anonymization on hard delete, defensive only in v1"
        bigint session_id FK "nullable, SET_NULL"
        string tool_name
        jsonb arguments "sanitized, no secrets"
        string result_status
        string error_code "nullable"
        uuid correlation_id
        integer duration_ms
        datetime created_at
    }
