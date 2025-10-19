# boards/ws_auth.py
from urllib.parse import parse_qs
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from channels.db import database_sync_to_async

# Dùng SimpleJWT để verify token (khuyên dùng)
try:
    from rest_framework_simplejwt.backends import TokenBackend
    _use_sjwt = True
except Exception:
    _use_sjwt = False
    import jwt  # fallback nếu bạn chưa cài simplejwt

User = get_user_model()

class JWTAuthMiddleware:
    """ASGI middleware: thêm user vào scope dựa trên ?token=..."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Chỉ xử lý websocket
        if scope.get("type") != "websocket":
            return await self.app(scope, receive, send)

        # Lấy token từ querystring
        query = parse_qs((scope.get("query_string") or b"").decode())
        token = (query.get("token") or [None])[0]

        user = None
        if token:
            try:
                if _use_sjwt:
                    # Verify với SimpleJWT
                    signing_key = settings.SIMPLE_JWT.get("SIGNING_KEY", settings.SECRET_KEY)
                    backend = TokenBackend(algorithm="HS256", signing_key=signing_key)
                    payload = backend.decode(token, verify=True)
                else:
                    # Fallback: verify với SECRET_KEY (chỉ khi bạn thực sự ký access token bằng SECRET_KEY)
                    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])

                user_id = payload.get("user_id") or payload.get("sub")
                if user_id:
                    user = await self._get_user(user_id)
            except Exception:
                user = None

        # Gán user vào scope
        scope = dict(scope)
        scope["user"] = user or AnonymousUser()

        return await self.app(scope, receive, send)

    @database_sync_to_async
    def _get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
