from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config import get_settings


class AuthManager:
    def __init__(self):
        settings = get_settings()
        self.serializer = URLSafeTimedSerializer(settings.secret_key)
        self.password = settings.app_password
        self.max_age = settings.session_max_age

    def verify_password(self, password: str) -> bool:
        return password == self.password

    def create_session_token(self) -> str:
        return self.serializer.dumps({"authenticated": True})

    def verify_session(self, token: str) -> bool:
        try:
            data = self.serializer.loads(token, max_age=self.max_age)
            return data.get("authenticated", False)
        except (BadSignature, SignatureExpired):
            return False


_auth_manager: AuthManager | None = None


def get_auth_manager() -> AuthManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


async def require_auth(request: Request):
    """Dependency that requires authentication."""
    token = request.cookies.get("session")
    if not token or not get_auth_manager().verify_session(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )


def check_auth(request: Request) -> bool:
    """Check if request is authenticated without raising."""
    token = request.cookies.get("session")
    if not token:
        return False
    return get_auth_manager().verify_session(token)
