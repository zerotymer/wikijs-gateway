import hmac

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings
from app.problems import ProblemError

_bearer = HTTPBearer(auto_error=False)


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    if credentials is None:
        raise ProblemError(
            401,
            "unauthorized",
            "Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Constant-time compare; encode first so non-ASCII input cannot raise.
    if not hmac.compare_digest(
        credentials.credentials.encode(), settings.gateway_admin_token.encode()
    ):
        raise ProblemError(403, "forbidden", "Invalid token")
