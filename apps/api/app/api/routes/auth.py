"""Authentication routes: register, login, Google OAuth callback, me."""

import secrets
from hmac import compare_digest
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.services import auth as auth_service
from app.services import google_oauth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    return auth_service.register_user(db, payload)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    return auth_service.authenticate_user(db, payload)


@router.get("/google/config")
def google_config() -> dict[str, bool]:
    """Expose only whether the optional provider can be used."""
    return {"enabled": google_oauth.is_google_oauth_configured()}


@router.get("/google/start")
def google_start() -> RedirectResponse:
    """Start server-side authorization-code flow with CSRF state validation."""
    if not google_oauth.is_google_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(google_oauth.authorization_url(state), status_code=302)
    redirect_uri = get_settings().google_redirect_uri or ""
    response.set_cookie(
        "pcc_google_oauth_state",
        state,
        max_age=600,
        httponly=True,
        secure=redirect_uri.startswith("https://"),
        samesite="lax",
        # The production reverse proxy exposes this API below /api while FastAPI
        # receives /auth. Root scope makes the state cookie work in both forms.
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Validate Google's callback and hand the normal PCC JWT to the web app."""
    settings = get_settings()
    login_url = f"{settings.web_app_url.rstrip('/')}/login"
    expected_state = request.cookies.get("pcc_google_oauth_state")
    if error or not code or not state or not expected_state or not compare_digest(state, expected_state):
        response = RedirectResponse(
            f"{login_url}?{urlencode({'google_error': 'Google sign-in was cancelled or expired.'})}",
            status_code=302,
        )
        response.delete_cookie("pcc_google_oauth_state", path="/")
        return response

    try:
        profile = await google_oauth.get_google_profile(code)
        auth = auth_service.authenticate_google_user(db, **profile)
    except HTTPException:
        response = RedirectResponse(
            f"{login_url}?{urlencode({'google_error': 'Google sign-in could not be verified.'})}",
            status_code=302,
        )
        response.delete_cookie("pcc_google_oauth_state", path="/")
        return response

    # Fragments are not sent back to a server, unlike a query parameter, so
    # the bearer token stays out of proxy/access logs and Next.js routing logs.
    response = RedirectResponse(
        f"{settings.web_app_url.rstrip('/')}/auth/google/callback"
        f"#access_token={auth.access_token}",
        status_code=302,
    )
    response.delete_cookie("pcc_google_oauth_state", path="/")
    return response


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return auth_service.build_user_response(current_user)
