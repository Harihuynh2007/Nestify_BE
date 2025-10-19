# boards/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
import uuid, os

from django.utils import timezone
from django.utils.text import get_valid_filename

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
User = get_user_model()


# ========= Enums (chuẩn hoá text choices, tránh typo) =========
class WorkspaceRole(models.TextChoices):
    ADMIN = 'admin', 'Admin'
    MEMBER = 'member', 'Member'


class BoardVisibility(models.TextChoices):
    PRIVATE = 'private', 'Private'
    WORKSPACE = 'workspace', 'Workspace'
    PUBLIC = 'public', 'Public'


class BoardRole(models.TextChoices):
    ADMIN = 'admin', 'Admin'
    EDITOR = 'editor', 'Editor'
    VIEWER = 'viewer', 'Viewer'


# ==================== Core models ====================
class BoardCreationPolicy(models.TextChoices):
    MEMBERS = "members", "Members can create boards"
    ADMINS  = "admins",  "Only workspace admins"
    OWNER   = "owner",   "Only workspace owner"

class Workspace(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owned_workspaces"   # tiện truy xuất owner.owned_workspaces.all()
    )

    board_creation_policy = models.CharField(
        max_length=16,
        choices=BoardCreationPolicy.choices,
        default=BoardCreationPolicy.MEMBERS,
    )
    def can_create_board(self, user):
        """Check if user có quyền tạo board theo policy"""
        if self.owner_id == user.id:
            return True
        
        if self.board_creation_policy == BoardCreationPolicy.OWNER:

            return False
        
        # Check membership
        try:
            membership = WorkspaceMembership.objects.get(workspace=self, user=user)
        except WorkspaceMembership.DoesNotExist:
            return False
        
        if self.board_creation_policy == BoardCreationPolicy.ADMINS:
            return membership.role == WorkspaceRole.ADMIN
        
        # MEMBERS policy - tất cả members đều được
        return True
    
    def __str__(self) -> str:
        return f"{self.name} (owner: {getattr(self.owner, 'username', self.owner_id)})"


class WorkspaceMembership(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='workspace_memberships'  # ws.workspace_memberships.all()
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='workspace_memberships'  # user.workspace_memberships.all()
    )
    role = models.CharField(
        max_length=10,
        choices=WorkspaceRole.choices,
        default=WorkspaceRole.MEMBER
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('workspace', 'user')

    def __str__(self) -> str:
        return f"{self.user_id} in ws {self.workspace_id} as {self.role}"


class Board(models.Model):
    name = models.CharField(max_length=255)
    background = models.TextField(blank=True)

    visibility = models.CharField(
        max_length=20,
        choices=BoardVisibility.choices,
        default=BoardVisibility.PRIVATE
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='boards'  # ws.boards.all()
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='boards_created'  # user.boards_created.all()
    )
    created_at = models.DateTimeField(auto_now_add=True)

    owned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='boards_owned',
        help_text='Current owner (can be transferred)'
    )

    # Quan hệ thành viên board qua bảng trung gian
    members = models.ManyToManyField(
        User,
        related_name='boards',         # user.boards.all()
        through='BoardMembership',
        blank=True
    )

    is_closed = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.name} (ws:{self.workspace_id})"

    def save(self, *args, **kwargs):
        # Auto-set owned_by = created_by lần đầu
        if not self.pk and not self.owned_by_id and self.created_by_id:
            self.owned_by = self.created_by
        super().save(*args, **kwargs)
    
    def get_owner(self):
        """Lấy owner hiện tại"""
        return self.owned_by or self.created_by
    
    def transfer_ownership(self, new_owner):
        """Transfer ownership sang user khác"""
        if not BoardMembership.objects.filter(board=self, user=new_owner).exists():
            # Tự động thêm new_owner vào board nếu chưa có
            BoardMembership.objects.create(
                board=self, 
                user=new_owner, 
                role=BoardRole.ADMIN
            )
        
        self.owned_by = new_owner
        self.save(update_fields=['owned_by'])

class List(models.Model):
    name = models.CharField(max_length=128)
    position = models.IntegerField(default=0)
    background = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, default='private')
    created_at = models.DateTimeField(auto_now_add=True)
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name='lists'  # board.lists.all()
    )

    def __str__(self) -> str:
        return f"{self.name} (board:{self.board_id})"


class Card(models.Model):
    name = models.CharField(max_length=255)
    background = models.TextField(blank=True)
    visibility = models.CharField(max_length=20, default='private')
    description = models.TextField(blank=True)
    due_date = models.DateTimeField(null=True, blank=True)
    completed = models.BooleanField(default=False)
    start_date = models.DateTimeField(null=True, blank=True)

    due_reminder_offset = models.IntegerField(null=True, blank=True)

    due_reminder_at = models.DateTimeField(null=True, blank=True)

    completed_at = models.DateTimeField(null=True, blank=True)

    recurrence = models.CharField(
        max_length=16,
        choices=[('never','Never'), ('daily','Daily'), ('weekly','Weekly'), ('monthly','Monthly')],
        default='never'
    )
    list = models.ForeignKey(
        List,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cards'    # list.cards.all()
    )

    STATUS_CHOICES = [
        ('doing', 'Doing'),
        ('done', 'Done'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='doing')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=False, related_name='cards_created')
    labels = models.ManyToManyField("Label", blank=True, related_name='cards')

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='CardMembership',
        through_fields=('card', 'user'),
        related_name='card_memberships',
        blank=True,
    )

    # Watchers - những người theo dõi card nhưng không được assign
    watchers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='watched_cards',
        blank=True,
    )

    position = models.IntegerField(default=0, db_index=True)  

    class Meta:
        indexes = [
            models.Index(fields=['list', 'position']),
            models.Index(fields=['due_date']),
            models.Index(fields=['created_by', 'list']),
            models.Index(fields=['due_reminder_at']),
        ]

    # ====== helpers ======
    def compute_due_reminder_at(self):
        if self.due_date and self.due_reminder_offset is not None:
            from django.utils import timezone
            return self.due_date - timezone.timedelta(minutes=self.due_reminder_offset)
        return None  

    def next_recurrence_due(self):
        """Tính due_date kế tiếp dựa vào recurrence."""
        if not self.due_date or self.recurrence == 'never':
            return None
        from dateutil.relativedelta import relativedelta
        delta = {
            'daily':   relativedelta(days=+1),
            'weekly':  relativedelta(weeks=+1),
            'monthly': relativedelta(months=+1),
        }.get(self.recurrence)
        return self.due_date + (delta or relativedelta())
      
        
    def __str__(self) -> str:
        return f"{self.name} (list:{self.list_id})"


class CardMembership(models.Model):
    """Intermediate model để lưu thêm thông tin về card membership"""
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='cardmembership_set')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cardmembership_user_set')
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='card_assignments_made'
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    role = models.CharField(
        max_length=20,
        choices=[
            ('assignee', 'Assignee'),
            ('reviewer', 'Reviewer'),
            ('observer', 'Observer')
        ],
        default='assignee'
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('card', 'user')

    def __str__(self) -> str:
        return f"{self.user_id} on card {self.card_id} as {self.role}"


# Activity tracking
class CardActivity(models.Model):
    ACTIVITY_TYPES = [
        ('member_added', 'Member Added'),
        ('member_removed', 'Member Removed'),
        ('card_moved', 'Card Moved'),
        ('card_updated', 'Card Updated'),
        ('comment_added', 'Comment Added'),
        ('due_date_changed', 'Due Date Changed'),
    ]

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='activities')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities_made')
    activity_type = models.CharField(max_length=20, choices=ACTIVITY_TYPES)
    description = models.TextField()
    target_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='card_activities_received'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"{self.activity_type} on card {self.card_id}"


class Label(models.Model):
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=20)
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='labels')

    def __str__(self) -> str:
        return f"{self.name or '(no name)'} [{self.color}] on board {self.board_id}"


class BoardMembership(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='board_memberships')
    role = models.CharField(
        max_length=10,
        choices=BoardRole.choices,
        default=BoardRole.VIEWER
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('board', 'user')

    def __str__(self) -> str:
        return f"{self.user_id} in board {self.board_id} as {self.role}"


class BoardInviteLink(models.Model):
    ROLE_CHOICES = [
        ('member', 'Member'),
        ('admin', 'Admin'),
        ('observer', 'Observer'),
    ]

    board = models.OneToOneField('Board', on_delete=models.CASCADE, related_name='invite_link')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='board_invites_created')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'boards_boardinvitelink'
        verbose_name = 'Board Invite Link'
        verbose_name_plural = 'Board Invite Links'

    def __str__(self):
        return f"Invite link for {self.board.name}"

    def is_expired(self):
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at


class Comment(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f"Comment {self.id} on card {self.card_id}"


# Add to your models.py
class Checklist(models.Model):
    card = models.ForeignKey('Card', on_delete=models.CASCADE, related_name='checklists')
    title = models.CharField(max_length=255, default='Checklist')
    position = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='checklists_created')

    class Meta:
        ordering = ['position', 'created_at']

    @property
    def completion_percentage(self):
        total_items = self.items.count()
        if total_items == 0:
            return 0
        completed_items = self.items.filter(completed=True).count()
        return round((completed_items / total_items) * 100)

    def __str__(self) -> str:
        return f"Checklist {self.title} for card {self.card_id}"


class ChecklistItem(models.Model):
    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name='items')
    text = models.TextField()
    completed = models.BooleanField(default=False)
    position = models.IntegerField(default=0)
    due_date = models.DateTimeField(null=True, blank=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_checklist_items')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='completed_checklist_items')

    class Meta:
        ordering = ['position', 'created_at']

    def __str__(self) -> str:
        return f"Item {self.id} on checklist {self.checklist_id}"


class Attachment(models.Model):
    ATTACHMENT_TYPES = [
        ('file', 'File Upload'),
        ('link', 'External Link'),
    ]

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='attachments')
    name = models.CharField(max_length=255)  # Tên hiển thị
    attachment_type = models.CharField(max_length=10, choices=ATTACHMENT_TYPES, default='file')

    # Cho file upload
    def safe_upload_to(instance, filename):
        safe_name = get_valid_filename(filename)
        return f"attachments/{instance.card.id}/{safe_name}"

    file = models.FileField(upload_to=safe_upload_to)
    file_size = models.BigIntegerField(null=True, blank=True)  # Size in bytes
    mime_type = models.CharField(max_length=100, null=True, blank=True)

    # Cho external link
    url = models.URLField(max_length=1000, null=True, blank=True)

    # Metadata
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='attachments_uploaded'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Cho cover image
    is_cover = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.card.name}"

    @property
    def file_size_human(self):
        size = self.file_size
        if not size:
            return None
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    @property
    def is_image(self):
        if self.mime_type:
            return self.mime_type.startswith('image/')
        return False
#===============Notifications================
class Notification(models.Model):
    """
    Một thông báo gửi tới 1 người dùng cụ thể.
    Có thể liên kết tới bất kỳ đối tượng nào (board, card, comment, ...).
    """
    LEVEL_CHOICES = [
        ("info", "Info"),       #VD: "Mr. A đã mời bạn vào board X"
        ("success", "Success"),  #VD: "Bạn đã được thêm vào board Y"
        ("warning", "Warning"),  #VD: "Hạn chót của card Z sắp đến"
        ("error", "Error"),      #VD: "Có lỗi xảy ra khi thực hiện hành động"
    ]

    # Người nhận
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )

    # Ai gây ra hành động (tuỳ chọn)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="notifications_as_actor",
        null=True, blank=True,
    )

    # Hành động ngắn gọn: "đã mời bạn vào board", "đã bình luận", ...
    verb = models.CharField(max_length=140)

    # Generic target (ví dụ: Board, Card, Comment)
    target_ct = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)    # target content type (board, card, comment, ...)
    target_id = models.CharField(max_length=64, null=True, blank=True)  # target object id
    target = GenericForeignKey("target_ct", "target_id")

    # Mức độ
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="info")

    # Trạng thái đọc
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    # Dữ liệu phụ (vd: tên board, tên card, URL deep-link,…)
    # Nếu dùng PostgreSQL có thể chuyển sang JSONField native
    data = models.JSONField(default=dict, blank=True)

    # Thời điểm
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
        ]

    def mark_read(self, commit=True):
        from django.utils import timezone
        self.is_read = True
        if not self.read_at:
            self.read_at = timezone.now()
        if commit:
            self.save(update_fields=["is_read", "read_at", "updated_at"])

    def __str__(self):
        return f"[{self.level}] to={self.recipient_id}: {self.verb}"