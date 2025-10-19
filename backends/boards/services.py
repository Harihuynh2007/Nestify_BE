from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils import timezone
from asgiref.sync import async_to_sync

channel_layer = get_channel_layer()

import logging

from .models import Notification, Card, CardMembership
from boards.models import Notification
from boards.serializers import NotificationSerializer

logger = logging.getLogger(__name__)

User = get_user_model()


def broadcast_notification(notification: Notification):
    """Gửi 1 notification tới group user_{id}."""
    group = f"user_{notification.recipient_id}"
    payload = NotificationSerializer(notification).data
    async_to_sync(channel_layer.group_send)(
        group,
        {"type": "notification.message", "payload": payload},
    )


def _broadcast_many(notifications):
    """Best-effort: broadcast danh sách notification, log nếu lỗi."""
    for n in notifications:
        try:
            broadcast_notification(n)
        except Exception as e:
            logger.error(f"Failed to broadcast notification {n.id}: {e}")


def _collect_recipients(actor, card):
    """
    Tập hợp recipients: owner + watchers + members, bỏ actor, unique theo id.
    Yêu cầu các quan hệ: card.created_by, card.watchers, card.members
    """
    recips = {}

    # Luôn add owner
    if getattr(card, "created_by_id", None):
        recips[card.created_by_id] = card.created_by

    # Watchers
    if hasattr(card, "watchers"):
        for u in card.watchers.exclude(id=actor.id).only("id"):
            recips[u.id] = u

    # Members/assignees
    if hasattr(card, "members"):
        for u in card.members.exclude(id=actor.id).only("id"):
            recips[u.id] = u

    return list(recips.values())


def notify_new_comment(actor, card, comment):
    """
    Tạo Notification cho tất cả recipients liên quan, và chỉ broadcast
    SAU KHI transaction hiện tại commit thành công.
    """
    recipients = _collect_recipients(actor, card)
    if not recipients:
        return

    created = []

    # Tạo notifications trong transaction hiện tại
    with transaction.atomic():
        for user in recipients:
            n = Notification.objects.create(
                actor=actor,
                recipient=user,
                level="info",
                verb=f"commented on {card.name}",
                target=card,
                data={
                    "cardId": card.id,
                    "commentId": comment.id,
                    "type": "comment_added",
                    "message": getattr(comment, "content", "")[:100],
                    "action_url": f"/cards/{card.id}",
                },
            )
            created.append(n)

        # Chỉ broadcast sau khi commit OK
        transaction.on_commit(lambda: _broadcast_many(created))

# ============================================================
# 🔔 Helper: Gửi Notification đến user
# ============================================================

def _notify_user(recipient, verb, level="info", target=None, data=None):
    """
    Tạo notification và gửi realtime qua WebSocket tới người dùng.
    """
    n = Notification.objects.create(
        actor=None,
        recipient=recipient,
        verb=verb,
        level=level,
        target=target,
        data=data or {},
    )
    async_to_sync(channel_layer.group_send)(
        f"user_{recipient.id}",
        {
            "type": "notification.new",
            "event": "notification.new",
            "payload": {
                "id": n.id,
                "verb": n.verb,
                "level": n.level,
                "data": n.data,
                "created_at": n.created_at.isoformat(),
            },
        },
    )
    return n


# ============================================================
# 📅 Reminder Scheduling
# ============================================================

def schedule_due_reminder(card):
    """
    Dựng logic 'schedule' reminder cho card.
    - Nếu có Celery: có thể dùng apply_async(eta=card.due_reminder_at)
    - Nếu không có Celery: có thể chạy cron job quét mỗi phút.
    """
    if not card.due_reminder_at:
        return  # Không có thời điểm nhắc
    # Nếu bạn dùng Celery, uncomment đoạn sau:
    # from .tasks import send_due_reminder
    # send_due_reminder.apply_async(args=[card.id], eta=card.due_reminder_at)
    #
    # Nếu chưa có Celery → noop, reminder sẽ được xử lý bởi cron hoặc thủ công.
    return


def send_due_reminder_now(card):
    """
    Gửi notification ngay lập tức khi đến giờ nhắc hạn.
    Dùng cho cron job hoặc Celery task.
    """
    if not card.due_date or card.completed:
        return

    recipients = set()
    if card.created_by:
        recipients.add(card.created_by)
    # watchers
    recipients.update(card.watchers.all())
    # members
    for m in CardMembership.objects.filter(card=card, is_active=True).select_related("user"):
        recipients.add(m.user)

    verb = f"Card '{card.name}' is due soon!"
    data = {
        "type": "card_due_reminder",
        "message": f"'{card.name}' will be due at {card.due_date.strftime('%b %d, %I:%M %p')}",
        "action_url": f"/cards/{card.id}",
    }

    with transaction.atomic():
        for user in recipients:
            _notify_user(user, verb=verb, level="warning", target=card, data=data)


# ============================================================
# 🔁 Recurrence Utilities (optional)
# ============================================================

def handle_card_recurrence(card):
    """
    Khi card được đánh dấu completed=True và có recurrence != 'never',
    tự động tạo kỳ hạn kế tiếp.
    """
    if not card.recurrence or card.recurrence == "never":
        return

    next_due = card.next_recurrence_due()
    if not next_due:
        return

    card.due_date = next_due
    card.completed = False
    card.completed_at = None
    card.due_reminder_at = card.compute_due_reminder_at()
    card.save(update_fields=["due_date", "completed", "completed_at", "due_reminder_at"])

    # Ghi log activity (option)
    from .models import CardActivity
    CardActivity.objects.create(
        card=card,
        user=card.created_by,
        activity_type="due_date_changed",
        description=f"Auto scheduled next due date to {card.due_date.strftime('%b %d at %I:%M %p')}",
    )

    # Phát realtime để FE cập nhật ngay
    broadcast_card_update(card)


# ============================================================
# 📡 WebSocket broadcast (Board updates)
# ============================================================

def broadcast_card_update(card):
    """
    Phát realtime tới group board_{board_id} để FE đồng bộ ngay khi card thay đổi.
    """
    try:
        board_id = card.list.board_id if card.list else None
        if not board_id:
            return
        payload = {
            "type": "card.update",
            "event": "card.update",
            "payload": {
                "id": card.id,
                "name": card.name,
                "list": card.list_id,
                "start_date": card.start_date.isoformat() if card.start_date else None,
                "due_date": card.due_date.isoformat() if card.due_date else None,
                "due_reminder_at": card.due_reminder_at.isoformat() if card.due_reminder_at else None,
                "recurrence": card.recurrence,
                "completed": card.completed,
            },
        }
        async_to_sync(channel_layer.group_send)(f"board_{board_id}", payload)
    except Exception as e:
        import logging
        logging.warning(f"[broadcast_card_update] failed: {e}")


# ============================================================
# 🧹 Optional: Cron-style function
# ============================================================

def process_due_reminders():
    """
    Chạy mỗi phút (cron hoặc management command) để gửi reminder
    cho những card đến hạn nhắc.
    """
    now = timezone.now()
    cards = Card.objects.filter(
        due_reminder_at__lte=now,
        completed=False
    )
    for card in cards:
        send_due_reminder_now(card)