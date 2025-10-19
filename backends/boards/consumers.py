import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.db.models import Prefetch

logger = logging.getLogger(__name__)


class BoardConsumer(AsyncWebsocketConsumer):
    """
    WebSocket cho real-time board updates
    URL: ws://<host>/ws/boards/<board_id>/?token=<jwt_token>
    """

    async def connect(self):
        user = self.scope.get('user')

        # Reject anonymous users
        if not user or isinstance(user, AnonymousUser):
            await self.close(code=4401)
            return

        self.board_id = self.scope['url_route']['kwargs']['board_id']
        self.user = user
        self.user_id = user.id
        self.group_name = f'board_{self.board_id}'

        # Verify permission
        can_view = await self.check_board_permission()
        if not can_view:
            await self.close(code=4403)
            return

        # Join and accept
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Initial state
        await self.send_board_state()

        logger.info("User %s connected to board %s", self.user_id, self.board_id)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        uid = getattr(self, 'user_id', 'unknown')
        bid = getattr(self, 'board_id', 'unknown')
        logger.info("User %s disconnected from board %s", uid, bid)

    async def receive(self, text_data=None, bytes_data=None):
        """Optional client commands (e.g., ping)"""
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        if data.get('type') == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))

    # ==================== Event Handlers (must match 'type' exactly) ====================

    async def card_update(self, event):
        """
        Trigger via:
        await channel_layer.group_send(f"board_{board_id}", {
            "type": "card_update",
            "action": "created"|"updated"|"deleted",
            "card": {...},
            "list_id": event_optional_list_id,
        })
        """
        await self.send(text_data=json.dumps({
            'type': 'card_update',
            'action': event.get('action', 'updated'),
            'card': event.get('card'),
            'list_id': event.get('list_id'),
        }))

    async def list_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'list_update',
            'action': event.get('action', 'updated'),
            'list': event.get('list'),
        }))

    async def board_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'board_update',
            'board': event.get('board'),
        }))

    async def member_joined(self, event):
        await self.send(text_data=json.dumps({
            'type': 'member_joined',
            'user': event.get('user'),
        }))

    # ==================== Helpers ====================

    @database_sync_to_async
    def check_board_permission(self):
        """User must be able to view this board."""
        from .models import Board
        from .permissions import can_view_board

        try:
            board = Board.objects.get(id=self.board_id)
        except Board.DoesNotExist:
            return False
        return can_view_board(self.user, board)

    async def send_board_state(self):
        data = await self.get_board_data()
        await self.send(text_data=json.dumps({
            'type': 'initial_state',
            'board': data,
        }))

    @database_sync_to_async
    def get_board_data(self):
        """
        Get board with lists and their cards (ordered).
        Optional: include inbox cards (list is null) if your product uses an Inbox.
        """
        from .models import Board, List, Card

        try:
            # Prefetch cards for all lists in a single query
            cards_qs = Card.objects.order_by('position')
            lists_qs = (
                List.objects
                .filter(board_id=self.board_id)
                .order_by('position')
                .prefetch_related(Prefetch('card_set', queryset=cards_qs))
            )

            board = Board.objects.select_related('workspace').get(id=self.board_id)

            # Build lists + cards
            lists_data = []
            for lst in lists_qs:
                lists_data.append({
                    'id': lst.id,
                    'name': lst.name,
                    'position': lst.position,
                    'cards': [
                        {
                            'id': c.id,
                            'title': c.title,
                            'position': c.position,
                            'list': lst.id,
                        } for c in lst.card_set.all()
                    ]
                })

            # OPTIONAL: Inbox cards (uncomment if your app has Inbox)
            # inbox_cards = list(
            #     Card.objects.filter(list__isnull=True, board_id=self.board_id)
            #     .order_by('position')
            #     .values('id', 'title', 'position')
            # )

            return {
                'id': board.id,
                'name': board.name,
                'lists': lists_data,
                # 'inbox_cards': inbox_cards,
            }
        except Board.DoesNotExist:
            return None


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket cho real-time notifications
    URL: ws://<host>/ws/notifications/?token=<jwt_token>
    """

    async def connect(self):
        user = self.scope.get('user')
        if not user or isinstance(user, AnonymousUser):
            await self.close(code=4401)
            return

        self.user = user
        self.group_name = f"user_{user.id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.send_unread_count()

        logger.info("User %s connected to notifications", user.id)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        uid = getattr(getattr(self, 'user', None), 'id', 'unknown')
        logger.info("User %s disconnected from notifications", uid)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        cmd = data.get('type')
        if cmd == 'mark_read':
            ids = data.get('ids', [])
            await self._mark_read(ids)
            await self.send(text_data=json.dumps({'type': 'mark_read_success', 'ids': ids}))
        elif cmd == 'mark_all_read':
            count = await self._mark_all_read()
            await self.send(text_data=json.dumps({'type': 'mark_all_read_success', 'count': count}))
        elif cmd == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))

    # ==================== Event Handlers ====================

    async def notification_message(self, event):
        # event: {'type': 'notification_message', 'payload': {...}}
        await self.send(text_data=json.dumps(event.get('payload', {})))

    async def notification_count(self, event):
        await self.send(text_data=json.dumps({
            'type': 'unread_count',
            'count': event.get('count', 0),
        }))

    # ==================== Helpers ====================

    async def send_unread_count(self):
        count = await self._get_unread_count()
        await self.send(text_data=json.dumps({'type': 'unread_count', 'count': count}))

    @database_sync_to_async
    def _get_unread_count(self):
        from .models import Notification
        return Notification.objects.filter(recipient=self.user, is_read=False).count()

    @database_sync_to_async
    def _mark_read(self, ids):
        if not ids:
            return 0
        from .models import Notification
        from django.utils import timezone
        return Notification.objects.filter(
            recipient=self.user,
            id__in=ids,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())

    @database_sync_to_async
    def _mark_all_read(self):
        from .models import Notification
        from django.utils import timezone
        return Notification.objects.filter(
            recipient=self.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
