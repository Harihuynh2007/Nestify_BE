"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django

django.setup()

from boards.routing import websocket_urlpatterns
from boards.ws_auth import JWTAuthMiddleware
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

application = ProtocolTypeRouter({
'http': get_asgi_application(),
'websocket': AllowedHostsOriginValidator(
JWTAuthMiddleware(
URLRouter(websocket_urlpatterns)
)
),
})