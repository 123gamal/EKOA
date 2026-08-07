"""Refresh-token cookie helpers.

The refresh token is delivered in an ``HttpOnly`` cookie set by the API (never
by client-side JS). It is sent back automatically by the browser on
``/auth/refresh`` and ``/auth/logout``. The cookie is ``Secure`` in production
and ``SameSite=Lax`` so it is not leaked to other sites.
"""

from __future__ import annotations

from fastapi import Request, Response

from ekoa_config.settings import Settings

REFRESH_COOKIE_NAME = "refresh_token"


def build_refresh_token_cookie_kwargs(settings: Settings) -> dict:
    """Common cookie attributes for the refresh token."""
    max_age = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    return {
        "max_age": max_age,
        "httponly": True,
        "secure": settings.ENVIRONMENT.lower() == "production",
        "samesite": "lax",
        "path": "/",
    }


def set_refresh_token_cookie(response: Response, refresh_token: str, settings: Settings) -> None:
    """Attach the refresh token to the response as an HttpOnly cookie."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        **build_refresh_token_cookie_kwargs(settings),
    )


def clear_refresh_token_cookie(response: Response) -> None:
    """Expire the refresh-token cookie so the browser drops it."""
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/")


def get_refresh_token_from_cookie(request: Request) -> str | None:
    """Read the refresh token from the HttpOnly cookie, if present."""
    return request.cookies.get(REFRESH_COOKIE_NAME)
