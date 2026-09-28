"""Gemini Developer API adapter for the internal CARVIX Provider contract."""

import json
import re
from copy import deepcopy

from .provider import ProviderReply, ProviderUnavailable
from .sanitization import sanitize_payload
from .tool_schemas import TOOL_SCHEMAS


_RESERVED_CONTEXT_KEYS = {"tool_schemas", "tool_observations"}
_OBSERVATION_KEYS = {"tool_name", "success", "code", "message", "data", "errors"}
_RESULT_KEYS = ("success", "code", "message", "data", "errors")
_MIN_TIMEOUT_SECONDS = 1
_MAX_TIMEOUT_SECONDS = 30


class ProviderResponseError(Exception):
    """The SDK returned an unsupported or malformed response shape."""


def _validated_timeout_seconds(value):
    if isinstance(value, bool):
        raise ProviderUnavailable
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        seconds = int(value.strip())
    else:
        raise ProviderUnavailable
    if not _MIN_TIMEOUT_SECONDS <= seconds <= _MAX_TIMEOUT_SECONDS:
        raise ProviderUnavailable
    return seconds


def _load_sdk():
    """Import the optional SDK only when a configured Provider makes a call."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ProviderUnavailable from None
    return genai, types


def _json_native(value):
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError):
        raise ProviderResponseError from None


def _approved_schemas(context):
    schemas = context.get("tool_schemas")
    if not isinstance(schemas, list) or not schemas:
        raise ProviderResponseError

    declarations = []
    names = []
    seen = set()
    for schema in schemas:
        if not isinstance(schema, dict):
            raise ProviderResponseError
        name = schema.get("name")
        approved = TOOL_SCHEMAS.get(name)
        if not isinstance(name, str) or approved is None or schema != approved or name in seen:
            raise ProviderResponseError
        seen.add(name)
        names.append(name)
        declarations.append(schema)
    return names, declarations


def _gemini_parameters(schema):
    """Project a trusted internal contract to Gemini's supported schema shape."""
    parameters = schema.get("parameters")
    if (
        not isinstance(parameters, dict)
        or parameters.get("type") != "object"
        or not isinstance(parameters.get("properties"), dict)
        or not isinstance(parameters.get("required"), list)
        or parameters.get("additionalProperties") is not False
    ):
        raise ProviderResponseError

    properties = {}
    for name, definition in parameters["properties"].items():
        if not isinstance(name, str) or not isinstance(definition, dict):
            raise ProviderResponseError
        description = definition.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ProviderResponseError

        if "oneOf" in definition:
            if definition != {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "pattern": "^[0-9]+$"},
                ],
                "description": description,
            }:
                raise ProviderResponseError
            field_type = "integer"
        else:
            field_type = definition.get("type")
            if field_type not in {"integer", "string", "boolean"}:
                raise ProviderResponseError

        property_schema = {"type": field_type, "description": description}
        enum = definition.get("enum")
        if enum is not None:
            if not isinstance(enum, list) or not enum:
                raise ProviderResponseError
            property_schema["enum"] = deepcopy(enum)
        properties[name] = property_schema

    required = parameters["required"]
    if (
        any(not isinstance(name, str) or name not in properties for name in required)
        or len(set(required)) != len(required)
    ):
        raise ProviderResponseError
    return {
        "type": "object",
        "properties": properties,
        "required": deepcopy(required),
    }


def _application_context(context):
    safe_context = {
        key: value
        for key, value in context.items()
        if key not in _RESERVED_CONTEXT_KEYS
    }
    try:
        return sanitize_payload(safe_context)
    except Exception:
        raise ProviderResponseError from None


def _observation_result(observation, *, expected_name):
    if (
        not isinstance(observation, dict)
        or set(observation) != _OBSERVATION_KEYS
        or observation.get("tool_name") != expected_name
    ):
        raise ProviderResponseError

    result = {key: observation[key] for key in _RESULT_KEYS}
    if (
        not isinstance(result["success"], bool)
        or not isinstance(result["code"], str)
        or not isinstance(result["message"], str)
        or (result["data"] is not None and not isinstance(result["data"], dict))
        or (result["errors"] is not None and not isinstance(result["errors"], dict))
    ):
        raise ProviderResponseError
    try:
        return _json_native(sanitize_payload(result))
    except Exception:
        raise ProviderResponseError from None


_UNSUPPORTED_PART_FIELDS = (
    "audio_transcription",
    "inline_data",
    "file_data",
    "function_response",
    "executable_code",
    "code_execution_result",
    "tool_call",
    "tool_response",
    "video_metadata",
    "media_processing",
    "media_resolution",
    "part_metadata",
    "speech_metadata",
)


def _has_unsupported_part_data(part, *, allowed_field):
    if any(getattr(part, field, None) is not None for field in _UNSUPPORTED_PART_FIELDS):
        return True
    return any(
        getattr(part, field, None) is not None
        for field in ("text", "function_call")
        if field != allowed_field
    )


class GeminiProvider:
    """Translate between Gemini content and CARVIX's internal ProviderReply."""

    def __init__(self, *, api_key, model, timeout_seconds):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderUnavailable
        if not isinstance(model, str) or not model.strip():
            raise ProviderUnavailable
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._timeout_seconds = _validated_timeout_seconds(timeout_seconds)
        self._contents = None
        self._initial_message = None
        self._initial_system_prompt = None
        self._schema_names = None
        self._observation_count = 0
        self._pending_response_content = None
        self._pending_function_name = None
        self._pending_function_id = None
        self._finished = False

    def _add_observation(self, context, types):
        observations = context.get("tool_observations")
        if not isinstance(observations, list):
            raise ProviderResponseError

        if self._contents is None:
            if observations:
                raise ProviderResponseError
            return

        if (
            self._pending_response_content is None
            or self._pending_function_name is None
            or len(observations) != self._observation_count + 1
        ):
            raise ProviderResponseError

        result = _observation_result(
            observations[-1],
            expected_name=self._pending_function_name,
        )
        function_response_fields = {
            "name": self._pending_function_name,
            "response": result,
        }
        if self._pending_function_id is not None:
            function_response_fields["id"] = self._pending_function_id
        function_response = types.FunctionResponse(**function_response_fields)
        tool_part = types.Part(function_response=function_response)
        tool_content = types.Content(role="tool", parts=[tool_part])
        self._contents.extend((self._pending_response_content, tool_content))
        self._pending_response_content = None
        self._pending_function_name = None
        self._pending_function_id = None
        self._observation_count += 1

    def _ensure_conversation(self, *, message, system_prompt, context, types):
        if not isinstance(message, str) or not message.strip():
            raise ProviderResponseError
        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ProviderResponseError

        names, _ = _approved_schemas(context)
        if self._schema_names is None:
            self._schema_names = tuple(names)
        elif tuple(names) != self._schema_names:
            raise ProviderResponseError
        self._add_observation(context, types)

        if self._contents is None:
            safe_context = _application_context(context)
            context_json = json.dumps(
                safe_context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            user_text = (
                "CARVIX user message:\n"
                f"{message.strip()}\n\n"
                "Safe CARVIX application context (JSON):\n"
                f"{context_json}"
            )
            self._contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=user_text)],
                )
            ]
            self._initial_message = message.strip()
            self._initial_system_prompt = system_prompt
        elif (
            message.strip() != self._initial_message
            or system_prompt != self._initial_system_prompt
        ):
            raise ProviderResponseError

    def _config(self, *, system_prompt, tool, types):
        function_calling = types.FunctionCallingConfig(
            mode="AUTO",
        )
        return types.GenerateContentConfig(
            system_instruction=system_prompt,
            candidate_count=1,
            tools=[tool],
            tool_config=types.ToolConfig(function_calling_config=function_calling),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

    def _parse_response(self, response, types):
        if not isinstance(response, types.GenerateContentResponse):
            raise ProviderResponseError
        candidates = response.candidates
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ProviderResponseError

        candidate = candidates[0]
        if (
            not isinstance(candidate, types.Candidate)
            or candidate.finish_reason != types.FinishReason.STOP
            or not isinstance(candidate.content, types.Content)
            or candidate.content.role != "model"
            or not isinstance(candidate.content.parts, list)
            or len(candidate.content.parts) != 1
        ):
            raise ProviderResponseError

        content = candidate.content
        part = content.parts[0]
        if not isinstance(part, types.Part):
            raise ProviderResponseError

        function_call = part.function_call
        text = part.text
        if function_call is not None:
            if (
                not isinstance(function_call, types.FunctionCall)
                or _has_unsupported_part_data(part, allowed_field="function_call")
                or not isinstance(function_call.name, str)
                or not function_call.name.strip()
                or not isinstance(function_call.args, dict)
                or bool(function_call.partial_args)
                or function_call.will_continue is True
            ):
                raise ProviderResponseError
            arguments = _json_native(sanitize_payload(function_call.args))
            if not isinstance(arguments, dict):
                raise ProviderResponseError
            call_id = function_call.id
            if call_id is not None and (
                not isinstance(call_id, str) or not call_id.strip()
            ):
                raise ProviderResponseError
            self._pending_response_content = content
            self._pending_function_name = function_call.name
            self._pending_function_id = call_id
            return ProviderReply(
                tool_call={
                    "name": function_call.name,
                    "arguments": arguments,
                }
            )

        if (
            not isinstance(text, str)
            or not text.strip()
            or getattr(part, "thought", False) is True
            or _has_unsupported_part_data(part, allowed_field="text")
        ):
            raise ProviderResponseError
        self._finished = True
        return ProviderReply(text=text.strip())

    def generate(self, *, message, system_prompt, context):
        if self._finished:
            raise ProviderResponseError
        if not isinstance(context, dict):
            raise ProviderResponseError

        genai, types = _load_sdk()
        self._ensure_conversation(
            message=message,
            system_prompt=system_prompt,
            context=context,
            types=types,
        )
        _, declarations = _approved_schemas(context)
        tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=schema["name"],
                    description=schema["description"],
                    parameters_json_schema=_gemini_parameters(schema),
                )
                for schema in declarations
            ]
        )
        config = self._config(
            system_prompt=system_prompt,
            tool=tool,
            types=types,
        )
        http_options = types.HttpOptions(
            timeout=self._timeout_seconds * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        )

        client = None
        try:
            client = genai.Client(api_key=self._api_key, http_options=http_options)
            response = client.models.generate_content(
                model=self._model,
                contents=self._contents,
                config=config,
            )
        except Exception:
            # SDK exception strings can contain request, credential, or user data.
            raise ProviderUnavailable from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        return self._parse_response(response, types)
