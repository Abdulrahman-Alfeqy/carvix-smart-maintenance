"""Mocked Google SDK coverage for the request-local Gemini adapter."""

import copy
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .agent import _parse_reply
from .live_provider import GeminiProvider, ProviderResponseError
from .provider import ProviderReply, ProviderUnavailable, get_provider
from .tool_schemas import TOOL_SCHEMAS


@dataclass
class FakeFunctionDeclaration:
    name: str
    description: str
    parameters_json_schema: dict


@dataclass
class FakeTool:
    function_declarations: list


@dataclass
class FakeFunctionCallingConfig:
    mode: str


@dataclass
class FakeToolConfig:
    function_calling_config: FakeFunctionCallingConfig


@dataclass
class FakeAutomaticFunctionCallingConfig:
    disable: bool


@dataclass
class FakeGenerateContentConfig:
    system_instruction: str
    candidate_count: int
    tools: list
    tool_config: FakeToolConfig
    automatic_function_calling: FakeAutomaticFunctionCallingConfig


@dataclass
class FakeHttpRetryOptions:
    attempts: int


@dataclass
class FakeHttpOptions:
    timeout: int
    retry_options: FakeHttpRetryOptions


@dataclass
class FakeFunctionCall:
    name: str | None = None
    args: object = None
    id: str | None = None
    partial_args: list | None = None
    will_continue: bool | None = None


@dataclass
class FakeFunctionResponse:
    name: str
    response: dict
    id: str | None = None


@dataclass
class FakePart:
    text: str | None = None
    function_call: FakeFunctionCall | None = None
    thought: bool = False
    thought_signature: str | None = None
    function_response: FakeFunctionResponse | None = None
    audio_transcription: object = None
    inline_data: object = None
    file_data: object = None
    executable_code: object = None
    code_execution_result: object = None
    tool_call: object = None
    tool_response: object = None
    video_metadata: object = None
    media_processing: object = None
    media_resolution: object = None
    part_metadata: object = None
    speech_metadata: object = None

    @classmethod
    def from_text(cls, *, text):
        return cls(text=text)


@dataclass
class FakeContent:
    role: str
    parts: list


@dataclass
class FakeCandidate:
    content: FakeContent
    finish_reason: str


@dataclass
class FakeGenerateContentResponse:
    candidates: list | None


class FakeSDKTypes:
    FunctionDeclaration = FakeFunctionDeclaration
    Tool = FakeTool
    FunctionCallingConfig = FakeFunctionCallingConfig
    ToolConfig = FakeToolConfig
    AutomaticFunctionCallingConfig = FakeAutomaticFunctionCallingConfig
    GenerateContentConfig = FakeGenerateContentConfig
    HttpRetryOptions = FakeHttpRetryOptions
    HttpOptions = FakeHttpOptions
    FunctionCall = FakeFunctionCall
    FunctionResponse = FakeFunctionResponse
    Part = FakePart
    Content = FakeContent
    Candidate = FakeCandidate
    GenerateContentResponse = FakeGenerateContentResponse
    FinishReason = SimpleNamespace(STOP="STOP")


class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        if not self.responses:
            raise AssertionError("Unexpected additional Gemini request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)
        self.close = Mock()


def schema_context(names=None, *, observations=None):
    names = tuple(TOOL_SCHEMAS) if names is None else tuple(names)
    return {
        "username": "safe-owner",
        "role": "OWNER",
        "vehicles": [{"id": 7, "license_plate": "SAFE-7"}],
        "tool_schemas": [copy.deepcopy(TOOL_SCHEMAS[name]) for name in names],
        "tool_observations": [] if observations is None else observations,
    }


def final_response(text="CARVIX response", *, finish_reason="STOP"):
    return FakeGenerateContentResponse(
        candidates=[
            FakeCandidate(
                content=FakeContent(role="model", parts=[FakePart(text=text)]),
                finish_reason=finish_reason,
            )
        ]
    )


def function_response(name, arguments, *, call_id="call-1"):
    return FakeGenerateContentResponse(
        candidates=[
            FakeCandidate(
                content=FakeContent(
                    role="model",
                    parts=[FakePart(function_call=FakeFunctionCall(name, arguments, call_id))],
                ),
                finish_reason="STOP",
            )
        ]
    )


class GeminiSettingsTests(SimpleTestCase):
    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_keeps_provider_unavailable_without_loading_sdk(self):
        with patch("apps.ai_agent.live_provider._load_sdk") as load_sdk:
            with self.assertRaises(ProviderUnavailable):
                get_provider()
        load_sdk.assert_not_called()

    @override_settings(
        GEMINI_API_KEY="   ",
        GEMINI_MODEL="test-model",
        GEMINI_TIMEOUT_SECONDS="20",
    )
    def test_blank_key_is_unavailable(self):
        with self.assertRaises(ProviderUnavailable):
            get_provider()

    @override_settings(
        GEMINI_API_KEY="local-test-key",
        GEMINI_MODEL="test-model",
        GEMINI_TIMEOUT_SECONDS="20",
    )
    def test_configured_values_select_live_provider_without_exposing_key(self):
        provider = get_provider()

        self.assertIsInstance(provider, GeminiProvider)
        self.assertEqual(provider._model, "test-model")
        self.assertEqual(provider._timeout_seconds, 20)
        self.assertNotIn("local-test-key", repr(provider))

    @override_settings(
        GEMINI_API_KEY="local-test-key",
        GEMINI_MODEL="gemini-flash-latest",
        GEMINI_TIMEOUT_SECONDS="20",
    )
    def test_authoritative_srs_model_is_the_default(self):
        with patch(
            "apps.ai_agent.provider.settings",
            SimpleNamespace(GEMINI_API_KEY="local-test-key"),
        ):
            provider = get_provider()
        self.assertEqual(provider._model, "gemini-flash-latest")
        self.assertEqual(provider._timeout_seconds, 20)

    def test_invalid_timeout_fails_safely_at_configuration_boundary(self):
        for timeout in ("", "0", "31", "NaN", True, 0, 31):
            with self.subTest(timeout=timeout), override_settings(
                GEMINI_API_KEY="local-test-key",
                GEMINI_MODEL="test-model",
                GEMINI_TIMEOUT_SECONDS=timeout,
            ):
                with self.assertRaises(ProviderUnavailable):
                    get_provider()

    def test_api_key_model_and_timeout_are_required_as_safe_values(self):
        with self.assertRaises(ProviderUnavailable):
            GeminiProvider(api_key=" ", model="test-model", timeout_seconds="20")
        with self.assertRaises(ProviderUnavailable):
            GeminiProvider(api_key="local-test-key", model=" ", timeout_seconds="20")
        for timeout in ("1", "30", 1, 30):
            provider = GeminiProvider(
                api_key="local-test-key",
                model="test-model",
                timeout_seconds=timeout,
            )
            self.assertGreaterEqual(provider._timeout_seconds, 1)
            self.assertLessEqual(provider._timeout_seconds, 30)


class GeminiSDKAdapterTests(SimpleTestCase):
    system_prompt = "CARVIX system instructions"

    def setUp(self):
        self.client = FakeClient([])
        self.client_factory = Mock(return_value=self.client)
        self.genai = SimpleNamespace(Client=self.client_factory)
        self.types = FakeSDKTypes
        self.sdk_patch = patch(
            "apps.ai_agent.live_provider._load_sdk",
            return_value=(self.genai, self.types),
        )
        self.sdk_patch.start()
        self.addCleanup(self.sdk_patch.stop)
        self.provider = GeminiProvider(
            api_key="mock-api-key-never-sent-as-content",
            model="gemini-flash-latest",
            timeout_seconds=20,
        )

    def reply(self, *, context=None, message="Help with my vehicle"):
        return self.provider.generate(
            message=message,
            system_prompt=self.system_prompt,
            context=schema_context() if context is None else context,
        )

    def test_live_request_uses_exact_role_filtered_schemas_and_safe_context(self):
        self.client.models.responses.append(final_response())
        reply = self.reply(
            context=schema_context(("list_available_service_slots",))
        )

        self.assertEqual(reply, ProviderReply(text="CARVIX response"))
        call = self.client.models.calls[0]
        self.assertEqual(call["model"], "gemini-flash-latest")
        config = call["config"]
        declarations = config.tools[0].function_declarations
        self.assertEqual([item.name for item in declarations], ["list_available_service_slots"])
        internal_parameters = TOOL_SCHEMAS["list_available_service_slots"]["parameters"]
        converted_parameters = declarations[0].parameters_json_schema
        self.assertEqual(
            set(converted_parameters["properties"]),
            set(internal_parameters["properties"]),
        )
        self.assertEqual(converted_parameters["type"], "object")
        self.assertEqual(converted_parameters["required"], ["service_type_id"])
        self.assertEqual(
            converted_parameters["properties"]["service_type_id"],
            {
                "type": "integer",
                "description": internal_parameters["properties"]["service_type_id"]["description"],
            },
        )
        self.assertEqual(
            converted_parameters["properties"]["preferred_date"],
            {
                "type": "string",
                "description": internal_parameters["properties"]["preferred_date"]["description"],
            },
        )
        self.assertFalse(internal_parameters["additionalProperties"])
        self.assertNotIn("additionalProperties", converted_parameters)
        self.assertNotIn("format", json.dumps(converted_parameters))
        self.assertNotIn("pattern", json.dumps(converted_parameters))
        serialized_schemas = json.dumps(
            [item.parameters_json_schema for item in declarations]
        )
        self.assertNotIn("user_id", serialized_schemas)
        self.assertNotIn("owner_id", serialized_schemas)
        self.assertNotIn("booked_by_agent", serialized_schemas)
        self.assertEqual(config.tool_config.function_calling_config.mode, "AUTO")
        self.assertTrue(config.automatic_function_calling.disable)
        self.assertEqual(config.candidate_count, 1)
        self.assertEqual(config.system_instruction, self.system_prompt)

        request_text = call["contents"][0].parts[0].text
        self.assertIn("Help with my vehicle", request_text)
        self.assertIn('"role":"OWNER"', request_text)
        self.assertNotIn("tool_schemas", request_text)
        self.assertNotIn("tool_observations", request_text)
        self.assertNotIn("mock-api-key-never-sent-as-content", request_text)
        self.client_factory.assert_called_once()
        self.client_factory.assert_called_with(
            api_key="mock-api-key-never-sent-as-content",
            http_options=FakeHttpOptions(
                timeout=20000,
                retry_options=FakeHttpRetryOptions(attempts=1),
            ),
        )
        self.client.close.assert_called_once()

    def test_all_three_internal_schemas_convert_without_callable_references(self):
        self.client.models.responses.append(final_response())

        self.reply()

        declarations = self.client.models.calls[0]["config"].tools[0].function_declarations
        self.assertEqual([declaration.name for declaration in declarations], list(TOOL_SCHEMAS))
        expected = {
            "check_required_maintenance": ({"vehicle_id": "integer"}, ["vehicle_id"]),
            "list_available_service_slots": (
                {"service_type_id": "integer", "preferred_date": "string"},
                ["service_type_id"],
            ),
            "book_maintenance_appointment": (
                {
                    "vehicle_id": "integer",
                    "service_type_id": "integer",
                    "slot_id": "integer",
                    "confirmation": "boolean",
                },
                ["vehicle_id", "service_type_id", "slot_id", "confirmation"],
            ),
        }
        for declaration in declarations:
            with self.subTest(name=declaration.name):
                internal_parameters = TOOL_SCHEMAS[declaration.name]["parameters"]
                expected_types, expected_required = expected[declaration.name]
                self.assertEqual(
                    declaration.description,
                    TOOL_SCHEMAS[declaration.name]["description"],
                )
                self.assertEqual(
                    declaration.parameters_json_schema["type"], "object"
                )
                self.assertEqual(
                    declaration.parameters_json_schema["required"], expected_required
                )
                self.assertEqual(
                    set(declaration.parameters_json_schema["properties"]),
                    set(expected_types),
                )
                self.assertFalse(internal_parameters["additionalProperties"])
                self.assertNotIn(
                    "additionalProperties", declaration.parameters_json_schema
                )
                for property_name, expected_type in expected_types.items():
                    internal_property = internal_parameters["properties"][property_name]
                    self.assertEqual(
                        declaration.parameters_json_schema["properties"][property_name],
                        {
                            "type": expected_type,
                            "description": internal_property["description"],
                        },
                    )
                self.assertEqual(
                    set(internal_parameters["required"]),
                    set(expected_required),
                )
                self.assertFalse(callable(declaration))

    def test_valid_final_text_becomes_only_internal_reply_data(self):
        self.client.models.responses.append(final_response("  Safe final text.  "))

        reply = self.reply()

        self.assertIs(type(reply), ProviderReply)
        self.assertEqual(reply.text, "Safe final text.")
        self.assertIsNone(reply.tool_call)
        self.assertNotIsInstance(reply, FakeGenerateContentResponse)

    def test_text_with_unexpected_part_metadata_is_rejected(self):
        self.client.models.responses.append(
            FakeGenerateContentResponse(
                candidates=[
                    FakeCandidate(
                        content=FakeContent(
                            role="model",
                            parts=[
                                FakePart(
                                    text="safe text",
                                    part_metadata={"source": "unexpected"},
                                )
                            ],
                        ),
                        finish_reason="STOP",
                    )
                ]
            )
        )

        with self.assertRaises(ProviderResponseError):
            self.reply()

    def test_empty_malformed_and_unsupported_responses_are_rejected(self):
        malformed = (
            object(),
            FakeGenerateContentResponse(candidates=None),
            FakeGenerateContentResponse(candidates=[]),
            FakeGenerateContentResponse(
                candidates=[
                    FakeCandidate(
                        content=FakeContent(role="model", parts=[FakePart(text="one")]),
                        finish_reason="STOP",
                    ),
                    FakeCandidate(
                        content=FakeContent(role="model", parts=[FakePart(text="two")]),
                        finish_reason="STOP",
                    ),
                ]
            ),
            final_response("  "),
            final_response("unsafe", finish_reason="MAX_TOKENS"),
            FakeGenerateContentResponse(
                candidates=[
                    FakeCandidate(
                        content=FakeContent(
                            role="model",
                            parts=[FakePart(text="private reasoning", thought=True)],
                        ),
                        finish_reason="STOP",
                    )
                ]
            ),
            FakeGenerateContentResponse(
                candidates=[FakeCandidate(content=None, finish_reason="STOP")]
            ),
        )
        for response in malformed:
            with self.subTest(response=type(response).__name__):
                self.provider = GeminiProvider(
                    api_key="mock-key", model="test-model", timeout_seconds=20
                )
                self.client = FakeClient([response])
                self.client_factory.return_value = self.client

                with self.assertRaises(ProviderResponseError):
                    self.reply()

    def test_one_valid_function_call_becomes_one_json_native_provider_request(self):
        args = {"vehicle_id": 7}
        self.client.models.responses.append(
            function_response("check_required_maintenance", args)
        )

        reply = self.reply()

        self.assertEqual(
            reply,
            ProviderReply(
                tool_call={
                    "name": "check_required_maintenance",
                    "arguments": args,
                }
            ),
        )
        self.assertEqual(json.loads(json.dumps(reply.tool_call)), reply.tool_call)
        self.assertEqual(self.client.close.call_count, 1)

    def test_function_arguments_are_sanitized_and_unknown_name_is_left_for_agent_refusal(self):
        self.client.models.responses.append(
            function_response(
                "unknown_tool",
                {"api_key": "never returned", "vehicle_id": 7},
            )
        )

        reply = self.reply()

        self.assertEqual(reply.tool_call["name"], "unknown_tool")
        self.assertNotEqual(reply.tool_call["arguments"]["api_key"], "never returned")
        self.assertEqual(_parse_reply(reply)[0], "tool")

    def test_missing_non_object_multi_mixed_and_partial_calls_are_rejected(self):
        malformed_parts = (
            FakePart(function_call=FakeFunctionCall("check_required_maintenance", None)),
            FakePart(function_call=FakeFunctionCall(None, {"vehicle_id": 7})),
            FakePart(function_call=FakeFunctionCall("check_required_maintenance", [7])),
            FakePart(
                function_call=FakeFunctionCall("check_required_maintenance", {"vehicle_id": 7}),
                text="also a completion",
            ),
            FakePart(
                function_call=FakeFunctionCall(
                    "check_required_maintenance",
                    {"vehicle_id": 7},
                    partial_args=[{"json_path": "vehicle_id"}],
                )
            ),
            FakePart(
                function_call=FakeFunctionCall(
                    "check_required_maintenance",
                    {"vehicle_id": 7},
                    will_continue=True,
                )
            ),
        )
        responses = [
            FakeGenerateContentResponse(
                candidates=[
                    FakeCandidate(
                        content=FakeContent(role="model", parts=[part]),
                        finish_reason="STOP",
                    )
                ]
            )
            for part in malformed_parts
        ]
        responses.append(
            FakeGenerateContentResponse(
                candidates=[
                    FakeCandidate(
                        content=FakeContent(
                            role="model",
                            parts=[
                                FakePart(
                                    function_call=FakeFunctionCall(
                                        "check_required_maintenance", {"vehicle_id": 7}
                                    )
                                ),
                                FakePart(
                                    function_call=FakeFunctionCall(
                                        "list_available_service_slots",
                                        {"service_type_id": 1},
                                    )
                                ),
                            ],
                        ),
                        finish_reason="STOP",
                    )
                ]
            )
        )

        for response in responses:
            with self.subTest(response=response):
                self.provider = GeminiProvider(
                    api_key="mock-key", model="test-model", timeout_seconds=20
                )
                self.client = FakeClient([response])
                self.client_factory.return_value = self.client

                with self.assertRaises(ProviderResponseError):
                    self.reply()

    def test_success_and_failure_observations_round_trip_as_exact_tool_responses(self):
        examples = (
            (
                "check_required_maintenance",
                True,
                {"vehicle_id": 7},
                {"vehicle_id": 7},
            ),
            (
                "list_available_service_slots",
                True,
                {"service_type_id": 2},
                {"slots": [{"id": 2}]},
            ),
            (
                "book_maintenance_appointment",
                True,
                {
                    "vehicle_id": 7,
                    "service_type_id": 2,
                    "slot_id": 3,
                    "confirmation": True,
                },
                {"appointment_id": 4},
            ),
            (
                "book_maintenance_appointment",
                False,
                {
                    "vehicle_id": 7,
                    "service_type_id": 2,
                    "slot_id": 3,
                    "confirmation": True,
                },
                None,
            ),
        )
        for index, (name, success, arguments, data) in enumerate(examples):
            with self.subTest(tool=name, success=success, index=index):
                self.provider = GeminiProvider(
                    api_key="mock-key", model="test-model", timeout_seconds=20
                )
                self.client = FakeClient(
                    [
                        function_response(name, arguments),
                        final_response("Backend result received."),
                    ]
                )
                self.client_factory.return_value = self.client
                first_context = schema_context()
                first = self.reply(context=first_context)
                self.assertEqual(first.tool_call["name"], name)

                observation = {
                    "tool_name": name,
                    "success": success,
                    "code": "ok" if success else "permission_denied",
                    "message": "Safe backend message",
                    "data": data,
                    "errors": None if success else {"vehicle_id": "Unavailable."},
                }
                second_context = schema_context(observations=[observation])
                second = self.reply(context=second_context)

                self.assertEqual(second, ProviderReply(text="Backend result received."))
                self.assertEqual(len(self.client.models.calls), 2)
                history = self.client.models.calls[1]["contents"]
                self.assertEqual(len(history), 3)
                self.assertEqual(history[1].role, "model")
                self.assertIsNotNone(history[1].parts[0].function_call)
                tool_part = history[2].parts[0]
                self.assertEqual(tool_part.function_response.name, name)
                self.assertEqual(
                    set(tool_part.function_response.response),
                    {"success", "code", "message", "data", "errors"},
                )
                self.assertEqual(
                    tool_part.function_response.response["success"],
                    success,
                )
                self.assertEqual(tool_part.function_response.id, "call-1")
                self.assertNotIn("tool_name", tool_part.function_response.response)
                self.assertNotIn("actor", json.dumps(tool_part.function_response.response))
                self.assertEqual(json.loads(json.dumps(observation)), observation)

    def test_observation_must_match_pending_tool_and_exact_result_shape(self):
        self.client.models.responses.append(
            function_response("check_required_maintenance", {"vehicle_id": 7})
        )
        self.reply()
        call_count = len(self.client.models.calls)

        with self.assertRaises(ProviderResponseError):
            self.reply(
                context=schema_context(
                    observations=[
                        {
                            "tool_name": "check_required_maintenance",
                            "success": "yes",
                            "code": "ok",
                            "message": "unsafe type",
                            "data": None,
                            "errors": None,
                        }
                    ]
                )
            )
        self.assertEqual(len(self.client.models.calls), call_count)

    def test_sdk_timeout_auth_rate_limit_and_network_failures_are_safe(self):
        errors = (
            TimeoutError("timeout with secret mock-key"),
            RuntimeError("429 invalid api key mock-key"),
            OSError("network path mentions mock-key"),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.provider = GeminiProvider(
                    api_key="mock-key", model="test-model", timeout_seconds=20
                )
                self.client = FakeClient([error])
                self.client_factory.return_value = self.client

                with self.assertRaises(ProviderUnavailable) as raised:
                    self.reply()

                self.assertEqual(str(raised.exception), "")
                self.assertNotIn("mock-key", str(raised.exception))
                self.client.close.assert_called_once()

    def test_client_construction_failure_is_safe_and_never_retried(self):
        self.client_factory.side_effect = RuntimeError("credential mock-key")

        with self.assertRaises(ProviderUnavailable) as raised:
            self.reply()

        self.assertEqual(str(raised.exception), "")
        self.assertEqual(self.client_factory.call_count, 1)

    def test_agent_contract_rejects_mixed_text_and_tool_reply(self):
        reply = ProviderReply(
            text="Ambiguous text",
            tool_call={"name": "check_required_maintenance", "arguments": {"vehicle_id": 7}},
        )

        self.assertEqual(_parse_reply(reply), ("invalid", None))
