from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    if credentials.credentials != settings.gateway_token:
        raise HTTPException(status_code=403, detail="Invalid token")
