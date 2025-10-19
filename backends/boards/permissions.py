# backends/boards/permissions.py
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from .models import (
    Board, BoardMembership,
    Workspace, WorkspaceMembership,WorkspaceRole,BoardRole
)

# ============
# Helpers
# ============

def _is_auth(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False))

def _is_workspace_owner(user, workspace: Workspace) -> bool:
    return _is_auth(user) and workspace and workspace.owner_id == user.id

def _workspace_role(user, workspace: Workspace):
    """
    Trả về 'admin' | 'member' | None
    """
    if not (_is_auth(user) and workspace):
        return None
    return WorkspaceMembership.objects.filter(
        user=user, workspace=workspace
    ).values_list("role", flat=True).first()

def _board_role(user, board: Board):
    """
    Trả về 'admin' | 'editor' | 'viewer' | None
    """
    if not (_is_auth(user) and board):
        return None
    return BoardMembership.objects.filter(
        user=user, board=board
    ).values_list("role", flat=True).first()

def get_user_role_on_board(board: Board, user):
    """
    Hoàn trả 'owner' nếu user là creator, ngược lại role từ BoardMembership,
    hoặc None nếu không thuộc board.
    """
    if not _is_auth(user):
        return None
    if board and board.created_by_id == user.id:
        return 'owner'
    return _board_role(user, board)

def get_user_workspace_role(user, workspace):
    if workspace.owner_id == user.id:
        return "owner"
    role = WorkspaceMembership.objects.filter(workspace=workspace, user=user)\
                                      .values_list("role", flat=True).first()
    if not role:
        # guest nếu chỉ là member của board trong workspace
        from .models import BoardMembership
        if BoardMembership.objects.filter(board__workspace=workspace, user=user).exists():
            return "guest"
        return None
    return role  # "admin" or "member"


# =========================
# Board-level permissions
# =========================

def _is_board_owner(user, board: Board) -> bool:
    owner = board.get_owner()
    return owner and owner.id == user.id

def can_create_board_in_workspace(user, workspace: Workspace) -> bool:
    return workspace.can_create_board(user)

def can_transfer_board_ownership(user, board: Board) -> bool:
    """Chỉ workspace owner hoặc board owner mới được chuyển ownership"""
    from .models import WorkspaceMembership
    if not user or not user.is_authenticated:
        return False
    if board.get_owner().id == user.id:
        return True
    if board.workspace.owner_id == user.id:
        return True
    # workspace admin cũng được (tuỳ policy)
    if WorkspaceMembership.objects.filter(workspace=board.workspace, user=user, role='admin').exists():
        return True
    return False


def can_view_board(user, board: Board) -> bool:
    """
    Quyền xem board:
    - public: ai cũng xem được (kể cả anonymous)
    - workspace: workspace owner hoặc thành viên workspace, hoặc thành viên/owner của board
    - private: creator, workspace owner, hoặc thành viên board
    """
    if not board:
        return False

    vis = board.visibility  # 'public' | 'workspace' | 'private'

    # Public: ai cũng xem
    if vis == 'public':
        return True

    # Các rule phía dưới yêu cầu user đăng nhập
    if not _is_auth(user):
        return False

    # Creator hoặc workspace owner luôn xem được
    if board.created_by_id == user.id:
        return True
    if _is_workspace_owner(user, board.workspace):
        return True

    # Thành viên workspace?
    ws_role = _workspace_role(user, board.workspace)

    if vis == 'workspace':
        # là member workspace (admin/member) thì xem được
        if ws_role in ('admin', 'member'):
            return True
        # hoặc là thành viên board
        if _board_role(user, board):
            return True
        return False

    if vis == 'private':
        # private chỉ cho creator, ws.owner, hoặc thành viên board
        if _board_role(user, board):
            return True
        return False

    # fallback an toàn
    return False


def can_edit_board(user, board: Board) -> bool:
    """
    Quyền chỉnh sửa board:
    - workspace owner, workspace admin
    - board creator
    - board admin/editor
    """
    if not (_is_auth(user) and board):
        return False

    if _is_workspace_owner(user, board.workspace):
        return True

    ws_role = _workspace_role(user, board.workspace)
    if ws_role == 'admin':
        return True

    if board.created_by_id == user.id:
        return True

    role = _board_role(user, board)
    if role in ('admin', 'editor'):
        return True

    return False


def can_delete_board(user, board: Board) -> bool:
    """
    Quyền xoá board:
    - workspace owner, workspace admin
    - board creator
    - board admin
    (tuỳ yêu cầu nghiệp vụ, bạn có thể siết còn owner+admin)
    """
    if not (_is_auth(user) and board):
        return False

    if _is_workspace_owner(user, board.workspace):
        return True

    ws_role = _workspace_role(user, board.workspace)
    if ws_role == 'admin':
        return True

    if board.created_by_id == user.id:
        return True

    role = _board_role(user, board)
    if role == 'admin':
        return True

    return False


# ==================================
# Check-style (raise PermissionDenied)
# ==================================

def check_board_view_permission(board: Board, user):
    if not can_view_board(user, board):
        raise PermissionDenied("You do not have permission to view this board.")

def check_board_edit_permission(board: Board, user):
    if not _is_auth(user):
        raise PermissionDenied("Authentication required.")
    if not can_edit_board(user, board):
        raise PermissionDenied("You must be an editor, admin, or owner to modify this board.")

def check_board_admin_permission(board: Board, user):
    if not _is_auth(user):
        raise PermissionDenied("Authentication required.")
    # admin-level: dùng can_delete_board như rule mạnh hơn, hoặc tự kiểm tra:
    if not (
        _is_workspace_owner(user, board.workspace)
        or _workspace_role(user, board.workspace) == 'admin'
        or board.created_by_id == user.id
        or _board_role(user, board) == 'admin'
    ):
        raise PermissionDenied("You must be an admin or the board creator to perform this action.")


# ==================================
# Workspace-level permissions
# ==================================

def check_workspace_view_permission(workspace: Workspace, user):
    if not _is_auth(user):
        raise PermissionDenied("Authentication required.")
    if _is_workspace_owner(user, workspace):
        return
    if WorkspaceMembership.objects.filter(workspace=workspace, user=user).exists():
        return
    raise PermissionDenied("You do not have permission to view this workspace.")

def check_workspace_admin_permission(workspace: Workspace, user):
    if not _is_auth(user):
        raise PermissionDenied("Authentication required.")
    if _is_workspace_owner(user, workspace):
        return
    if WorkspaceMembership.objects.filter(workspace=workspace, user=user, role='admin').exists():
        return
    raise PermissionDenied("You must be an admin or the workspace owner to perform this action.")

def check_workspace_member_permission(workspace: Workspace, user):
    if not _is_auth(user):
        raise PermissionDenied("Authentication required.")
    if _is_workspace_owner(user, workspace):
        return
    if WorkspaceMembership.objects.filter(workspace=workspace, user=user).exists():
        return
    raise PermissionDenied("You do not have permission to perform this action on this workspace.")


# ==================================
# Card-level permission (kéo/thả, sửa…)
# ==================================

def check_card_edit_permission(card, user):
    """
    Cho phép sửa card nếu:
    - Card trong inbox (list is None):
        + là creator, hoặc
        + user và creator có >=1 board chung
    - Card thuộc một list (tức thuộc một board):
        + user có quyền edit board đó (owner/ws-admin/board-admin/editor)
    """
    if not _is_auth(user):
        raise PermissionDenied("Authentication required.")

    # Card trong Inbox (không thuộc list)
    if not getattr(card, "list_id", None):
        if card.created_by_id == user.id:
            return
        # có board chung?
        user_boards = Board.objects.filter(
            Q(created_by=user) | Q(memberships__user=user)
        ).values_list("id", flat=True)
        creator_boards = Board.objects.filter(
            Q(created_by=card.created_by) | Q(memberships__user=card.created_by)
        ).values_list("id", flat=True)

        if set(user_boards).intersection(set(creator_boards)):
            return

        raise PermissionDenied("You don't have permission to modify this inbox card.")

    # Card thuộc list/board cụ thể
    board = card.list.board
    if can_edit_board(user, board):
        return
    
    owner = board.get_owner()
    if owner and owner.id == user.id:
        return True

    raise PermissionDenied("You must be an editor, admin, or owner to modify cards on this board.")
#=============Notification=================
class IsRecipient(BasePermission):
    """
    Chỉ cho phép người nhận xem/sửa/xoá thông báo của chính họ.
    """
    def has_object_permission(self, request, view, obj):
        return obj.recipient_id == request.user.id
    
def user_can_edit_board(user, board):
    """
    Kiểm tra quyền chỉnh sửa trên board (dùng trong serializer + view).
    """
    if not user or not user.is_authenticated:
        return False
    # Chủ workspace luôn có quyền
    if board.workspace.owner_id == user.id:
        return True

    # Là admin/member workspace → có quyền
    ws_role = WorkspaceMembership.objects.filter(user=user, workspace=board.workspace).values_list("role", flat=True).first()
    if ws_role in (WorkspaceRole.ADMIN, WorkspaceRole.MEMBER):
        return True

    # Là người tạo board → có quyền
    if board.created_by_id == user.id:
        return True

    # Là admin/editor board → có quyền
    bd_role = BoardMembership.objects.filter(user=user, board=board).values_list("role", flat=True).first()
    if bd_role in (BoardRole.ADMIN, BoardRole.EDITOR):
        return True

    return False    