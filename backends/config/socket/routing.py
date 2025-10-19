from django.urls import re_path
from backends.boards.consumers import BoardConsumer

websocket_urlpatterns = [
    re_path(r'ws/boards/(?P<board_id>\d+)/$', BoardConsumer.as_asgi()),
]