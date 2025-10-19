# backends/boards/decorators.py
from functools import wraps
from typing import Callable, Union

from django.shortcuts import get_object_or_404
from rest_framework.views import APIView

from .models import Board, Card, List
from .permissions import (
    check_board_view_permission,
    check_card_edit_permission,
    check_board_edit_permission,
    check_board_admin_permission,
    WorkspaceMembership,
    get_user_workspace_role,
)

Getter = Union[str, Callable]  # 'board_id' | lambda self, request, **kwargs: board

# --------- helpers ---------
def _resolve_request_and_self(args):
    """
    Trả về (self_obj_or_None, request, is_cbv)
    """
    if args and isinstance(args[0], APIView):
        return args[0], args[1], True
    return None, args[0], False

def _get_board_from_getter(getter: Getter, self_obj, request, **kwargs) -> Board:
    """
    getter:
      - str: tên kwarg chứa id (vd 'board_id') -> load Board
      - callable: nhận (self, request, **kwargs) -> trả về Board
    """
    if callable(getter):
        board = getter(self_obj, request, **kwargs)
        if not isinstance(board, Board):
            raise TypeError("board_getter callable must return a Board instance.")
        return board

    if isinstance(getter, str):
        if getter not in kwargs:
            raise KeyError(f"'{getter}' not found in URL kwargs: {list(kwargs.keys())}")
        return get_object_or_404(Board, pk=kwargs[getter])

    raise TypeError("board_getter must be a kwarg name (str) or a callable.")

def _get_card_from_getter(getter: Getter, self_obj, request, **kwargs) -> Card:
    if callable(getter):
        card = getter(self_obj, request, **kwargs)
        if not isinstance(card, Card):
            raise TypeError("card_getter callable must return a Card instance.")
        return card

    if isinstance(getter, str):
        if getter not in kwargs:
            raise KeyError(f"'{getter}' not found in URL kwargs: {list(kwargs.keys())}")
        return get_object_or_404(Card, pk=kwargs[getter])

    raise TypeError("card_getter must be a kwarg name (str) or a callable.")

def _get_board_from_list_kw(list_kw: str, kwargs) -> Board:
    if list_kw not in kwargs:
        raise KeyError(f"'{list_kw}' not found in URL kwargs: {list(kwargs.keys())}")
    lst = get_object_or_404(List.objects.select_related("board"), pk=kwargs[list_kw])
    return lst.board

# --------- decorators by board ---------
def require_board_viewer(board_getter: Getter = 'board_id'):
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(*args, **kwargs):
            self_obj, request, is_cbv = _resolve_request_and_self(args)
            board = _get_board_from_getter(board_getter, self_obj, request, **kwargs)
            check_board_view_permission(board, request.user)
            if is_cbv:
                setattr(self_obj, "board", board)
            return view_method(*args, **kwargs)
        return wrapper
    return decorator

def require_board_editor(board_getter: Getter = 'board_id'):
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(*args, **kwargs):
            self_obj, request, is_cbv = _resolve_request_and_self(args)
            board = _get_board_from_getter(board_getter, self_obj, request, **kwargs)
            check_board_edit_permission(board, request.user)
            if is_cbv:
                setattr(self_obj, "board", board)
            return view_method(*args, **kwargs)
        return wrapper
    return decorator

def require_board_admin(board_getter: Getter = 'board_id'):
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(*args, **kwargs):
            self_obj, request, is_cbv = _resolve_request_and_self(args)
            board = _get_board_from_getter(board_getter, self_obj, request, **kwargs)
            check_board_admin_permission(board, request.user)
            if is_cbv:
                setattr(self_obj, "board", board)
            return view_method(*args, **kwargs)
        return wrapper
    return decorator

# --------- decorators via list (khi URL chỉ có list_id) ---------
def require_board_viewer_from_list(list_kw: str = 'list_id'):
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(*args, **kwargs):
            self_obj, request, is_cbv = _resolve_request_and_self(args)
            board = _get_board_from_list_kw(list_kw, kwargs)
            check_board_view_permission(board, request.user)
            if is_cbv:
                setattr(self_obj, "board", board)
            return view_method(*args, **kwargs)
        return wrapper
    return decorator

def require_board_editor_from_list(list_kw: str = 'list_id'):
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(*args, **kwargs):
            self_obj, request, is_cbv = _resolve_request_and_self(args)
            board = _get_board_from_list_kw(list_kw, kwargs)
            check_board_edit_permission(board, request.user)
            if is_cbv:
                setattr(self_obj, "board", board)
            return view_method(*args, **kwargs)
        return wrapper
    return decorator

def require_board_admin_from_list(list_kw: str = 'list_id'):
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(*args, **kwargs):
            self_obj, request, is_cbv = _resolve_request_and_self(args)
            board = _get_board_from_list_kw(list_kw, kwargs)
            check_board_admin_permission(board, request.user)
            if is_cbv:
                setattr(self_obj, "board", board)
            return view_method(*args, **kwargs)
        return wrapper
    return decorator

# --------- decorators by card ---------
def require_card_editor(card_getter: Getter = 'card_id'):
    def decorator(view_method):
        @wraps(view_method)
        def wrapper(*args, **kwargs):
            self_obj, request, is_cbv = _resolve_request_and_self(args)
            card = _get_card_from_getter(card_getter, self_obj, request, **kwargs)
            check_card_edit_permission(card, request.user)
            if is_cbv:
                setattr(self_obj, "card", card)
                # Tiện nếu cần board/list:
                if card.list_id:
                    setattr(self_obj, "board", card.list.board)
            return view_method(*args, **kwargs)
        return wrapper
    return decorator

def can_invite_workspace_member(user, workspace):
    """Owner hoặc workspace admin"""
    return workspace.owner_id == user.id or \
           WorkspaceMembership.objects.filter(workspace=workspace, user=user, role='admin').exists()

def can_create_board_trello(user, workspace):
    """Theo policy"""
    if workspace.owner_id == user.id:
        return True
    role = get_user_workspace_role(user, workspace)
    if workspace.board_creation_policy == 'admins':
        return role == 'admin'
    if workspace.board_creation_policy == 'members':
        return role in ('admin', 'member')
    return False
