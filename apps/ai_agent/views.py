import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import csrf_protect

from apps.authentication.models import User

from .agent import respond_to_message


MAX_MESSAGE_LENGTH = 4000


def _json_response(*, success, code, message, data=None, errors=None, status=200):
    return JsonResponse(
        {
            "success": success,
            "code": code,
            "message": message,
            "data": data,
            "errors": errors,
        },
        status=status,
    )


@login_required
def chat_page(request):
    return render(
        request,
        "ai_agent/chat.html",
        {"chat_endpoint": reverse("ai_agent:chat-message")},
    )


@csrf_protect
def chat_message(request):
    if request.method != "POST":
        response = _json_response(
            success=False,
            code="method_not_allowed",
            message="Send a message with POST.",
            status=405,
        )
        response["Allow"] = "POST"
        return response
    if not request.user.is_authenticated:
        return _json_response(
            success=False,
            code="authentication_required",
            message="Sign in to use CARVIX chat.",
            status=401,
        )
    if request.user.role not in User.Role.values:
        return _json_response(
            success=False,
            code="permission_denied",
            message="Your account cannot use CARVIX chat.",
            status=403,
        )
    if request.content_type != "application/json":
        return _json_response(
            success=False,
            code="invalid_request",
            message="Send a JSON object containing a message.",
            errors={"message": "A JSON message is required."},
            status=400,
        )
    if len(request.body) > MAX_MESSAGE_LENGTH + 1024:
        return _json_response(
            success=False,
            code="message_too_long",
            message="Your message is too long.",
            errors={"message": f"Use at most {MAX_MESSAGE_LENGTH} characters."},
            status=400,
        )
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json_response(
            success=False,
            code="invalid_json",
            message="The request body must be valid JSON.",
            errors={"body": "Invalid JSON."},
            status=400,
        )
    if not isinstance(payload, dict):
        return _json_response(
            success=False,
            code="invalid_request",
            message="Send a JSON object containing a message.",
            errors={"body": "A JSON object is required."},
            status=400,
        )
    extra_fields = set(payload) - {"message"}
    if extra_fields:
        return _json_response(
            success=False,
            code="invalid_request",
            message="Only a message is accepted.",
            errors={field: "This field is not accepted." for field in sorted(extra_fields)},
            status=400,
        )
    message = payload.get("message")
    if not isinstance(message, str):
        return _json_response(
            success=False,
            code="invalid_request",
            message="Enter a text message.",
            errors={"message": "A text message is required."},
            status=400,
        )
    if not message.strip():
        return _json_response(
            success=False,
            code="invalid_request",
            message="Enter a message before sending.",
            errors={"message": "This field may not be blank."},
            status=400,
        )
    if len(message) > MAX_MESSAGE_LENGTH:
        return _json_response(
            success=False,
            code="message_too_long",
            message="Your message is too long.",
            errors={"message": f"Use at most {MAX_MESSAGE_LENGTH} characters."},
            status=400,
        )

    result = respond_to_message(user=request.user, message=message.strip())
    status = 200 if result.success else {
        "provider_unavailable": 503,
        "provider_error": 502,
    }.get(result.code, 400)
    return _json_response(
        success=result.success,
        code=result.code,
        message=result.message,
        data=result.data,
        errors=result.errors,
        status=status,
    )
