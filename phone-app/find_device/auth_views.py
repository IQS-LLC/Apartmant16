"""
Lumina Auth API — JWT-based authentication.

Endpoints (all under /auth/)
──────────────────────────────────────────────────
  POST /auth/register/   Create a new user account
  POST /auth/login/      Obtain access + refresh tokens
  POST /auth/refresh/    Rotate refresh token, get new access token
  GET  /auth/me/         Return current user profile
  PATCH /auth/me/        Update user profile
  POST /auth/logout/     Blacklist the refresh token

Token format
  Authorization: Bearer <access_token>
"""
from __future__ import annotations

import logging

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_exception_handler

from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import UserProfile

logger = logging.getLogger("lumina.auth")


# ─────────────────────────────────────────────────────────────────────────────
# Custom DRF exception handler — normalise to Lumina response format
# ─────────────────────────────────────────────────────────────────────────────

def drf_exception_handler(exc, context):
    response = drf_default_exception_handler(exc, context)
    if response is not None:
        detail = response.data.get("detail", str(response.data))
        response.data = {
            "ok":    False,
            "error": str(detail),
            "code":  "AUTH_ERROR",
        }
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class LuminaTokenObtainSerializer(TokenObtainPairSerializer):
    """Adds user details to the token response."""

    @classmethod
    def get_token(cls, user: User):
        token = super().get_token(user)
        token["username"] = user.username
        token["email"]    = user.email
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = _user_dict(self.user)
        return data


class LuminaTokenObtainView(TokenObtainPairView):
    serializer_class = LuminaTokenObtainSerializer


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _user_dict(user: User) -> dict:
    profile = getattr(user, "profile", None)
    return {
        "id":         user.id,
        "username":   user.username,
        "email":      user.email,
        "first_name": user.first_name,
        "last_name":  user.last_name,
        "theme":      profile.theme if profile else "dark",
        "push_notifications": (
            profile.push_notifications_enabled if profile else True
        ),
    }


def _ok(data: dict, status_code: int = status.HTTP_200_OK) -> Response:
    return Response({"ok": True, **data}, status=status_code)


def _err(message: str, code: str = "ERROR", status_code: int = 400) -> Response:
    return Response({"ok": False, "error": message, "code": code}, status=status_code)


# ─────────────────────────────────────────────────────────────────────────────
# Register
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def register(request: Request) -> Response:
    """
    Create a new Lumina account.

    Body: username, password, email (optional), first_name (optional)
    Returns: access + refresh tokens + user dict
    """
    username   = (request.data.get("username") or "").strip()
    password   = request.data.get("password") or ""
    email      = (request.data.get("email") or "").strip()
    first_name = (request.data.get("first_name") or "").strip()

    if not username:
        return _err("username is required", "INVALID_PARAM")
    if not password:
        return _err("password is required", "INVALID_PARAM")
    if len(username) < 3:
        return _err("username must be at least 3 characters", "INVALID_PARAM")
    if User.objects.filter(username=username).exists():
        return _err("Username already taken", "USERNAME_TAKEN", 409)
    if email and User.objects.filter(email=email).exists():
        return _err("Email already registered", "EMAIL_TAKEN", 409)

    # Validate password strength
    try:
        validate_password(password)
    except DjangoValidationError as exc:
        return _err(" ".join(exc.messages), "WEAK_PASSWORD")

    user = User.objects.create_user(
        username=username,
        password=password,
        email=email,
        first_name=first_name,
    )

    refresh = RefreshToken.for_user(user)
    logger.info("New user registered: %s", username)

    return _ok(
        {
            "access":  str(refresh.access_token),
            "refresh": str(refresh),
            "user":    _user_dict(user),
        },
        status_code=status.HTTP_201_CREATED,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Login  (delegates to simplejwt but adds user dict)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def login(request: Request) -> Response:
    """
    Authenticate with username + password.
    Returns access token (30 min) + refresh token (7 days, rotated).
    """
    serializer = LuminaTokenObtainSerializer(
        data=request.data, context={"request": request}
    )
    try:
        serializer.is_valid(raise_exception=True)
    except TokenError as exc:
        return _err(str(exc), "TOKEN_ERROR", 401)
    except serializers.ValidationError:
        return _err(
            "Invalid credentials. Check username and password.",
            "INVALID_CREDENTIALS",
            401,
        )

    data = serializer.validated_data
    logger.info("Login: %s", data["user"]["username"])
    return _ok(data)


# ─────────────────────────────────────────────────────────────────────────────
# Refresh
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([AllowAny])
def refresh_token(request: Request) -> Response:
    """
    Exchange a refresh token for a new access + refresh pair.
    The old refresh token is blacklisted (rotation enabled).
    """
    token_str = request.data.get("refresh") or ""
    if not token_str:
        return _err("refresh token is required", "INVALID_PARAM")

    try:
        token = RefreshToken(token_str)
        access = str(token.access_token)
        # rotate — blacklists old, generates new refresh
        token.blacklist()
        new_refresh = str(RefreshToken.for_user(
            User.objects.get(id=token.payload["user_id"])
        ))
    except (TokenError, InvalidToken) as exc:
        return _err(str(exc), "TOKEN_INVALID", 401)
    except Exception as exc:
        logger.exception("refresh_token error")
        return _err(str(exc), "SERVER_ERROR", 500)

    return _ok({"access": access, "refresh": new_refresh})


# ─────────────────────────────────────────────────────────────────────────────
# Me
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def me(request: Request) -> Response:
    """
    GET  — return the authenticated user's profile.
    PATCH — update theme or push_notifications.
    """
    user = request.user

    if request.method == "GET":
        return _ok({"user": _user_dict(user)})

    # PATCH — update mutable profile fields
    profile, _ = UserProfile.objects.get_or_create(user=user)
    updated = []

    if "theme" in request.data:
        theme = request.data["theme"]
        if theme not in ("dark", "light"):
            return _err("theme must be 'dark' or 'light'", "INVALID_PARAM")
        profile.theme = theme
        updated.append("theme")

    if "push_notifications" in request.data:
        profile.push_notifications_enabled = bool(request.data["push_notifications"])
        updated.append("push_notifications")

    if "first_name" in request.data:
        user.first_name = str(request.data["first_name"])[:50]
        user.save(update_fields=["first_name"])
        updated.append("first_name")

    if "last_name" in request.data:
        user.last_name = str(request.data["last_name"])[:50]
        user.save(update_fields=["last_name"])
        updated.append("last_name")

    profile.save()
    return _ok({"user": _user_dict(user), "updated": updated})


# ─────────────────────────────────────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout(request: Request) -> Response:
    """
    Blacklist the refresh token so it can no longer be used.
    The client should also discard its stored tokens.
    """
    token_str = request.data.get("refresh") or ""
    if not token_str:
        return _err("refresh token is required", "INVALID_PARAM")

    try:
        RefreshToken(token_str).blacklist()
    except (TokenError, InvalidToken):
        pass  # already invalid/expired — treat as logged out

    logger.info("Logout: %s", request.user.username)
    return _ok({"message": "Logged out successfully"})
