"""Internal JSON-native schemas for the approved CARVIX Tools."""


def _identifier_schema(description):
    # The provider-facing shape is an integer. Decimal strings are retained
    # for compatibility with the already-approved direct Handler contract.
    return {
        "oneOf": [
            {"type": "integer", "minimum": 1},
            {"type": "string", "pattern": "^[0-9]+$"},
        ],
        "description": description,
    }


TOOL_SCHEMAS = {
    "check_required_maintenance": {
        "name": "check_required_maintenance",
        "description": "Check required or overdue maintenance for one vehicle owned by the authenticated Owner.",
        "parameters": {
            "type": "object",
            "properties": {
                "vehicle_id": _identifier_schema("Positive identifier for the Owner's vehicle."),
            },
            "required": ["vehicle_id"],
            "additionalProperties": False,
        },
    },
    "list_available_service_slots": {
        "name": "list_available_service_slots",
        "description": (
            "List currently eligible service slots. Availability is global; "
            "a preferred date is validated but is not used to filter slots."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_type_id": _identifier_schema("Positive identifier for an existing service type."),
                "preferred_date": {
                    "type": "string",
                    "format": "date",
                    "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                    "description": "Optional ISO calendar date; currently validation-only.",
                },
            },
            "required": ["service_type_id"],
            "additionalProperties": False,
        },
    },
    "book_maintenance_appointment": {
        "name": "book_maintenance_appointment",
        "description": (
            "Book an appointment for the authenticated Owner's vehicle after "
            "explicit confirmation. The server supplies identity and AI attribution."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "vehicle_id": _identifier_schema("Positive identifier for the Owner's vehicle."),
                "service_type_id": _identifier_schema("Positive identifier for the requested service type."),
                "slot_id": _identifier_schema("Positive identifier for the available service slot."),
                "confirmation": {
                    "type": "boolean",
                    "description": "Must be the boolean true after the Owner explicitly confirms.",
                },
            },
            "required": [
                "vehicle_id",
                "service_type_id",
                "slot_id",
                "confirmation",
            ],
            "additionalProperties": False,
        },
    },
}
