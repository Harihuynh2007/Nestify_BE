from django.urls import re_path
from .consumers import NotificationConsumer, BoardConsumer

websocket_urlpatterns = [
    re_path(r"^ws/notifications/$", NotificationConsumer.as_asgi()),
    re_path(r"^ws/boards/(?P<board_id>\d+)/$", BoardConsumer.as_asgi()),
]
