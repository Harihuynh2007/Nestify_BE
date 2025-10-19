from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import Profile
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

@receiver(post_save, sender=User, dispatch_uid="auth_app_create_profile_once")
def ensure_user_profile(sender, instance, created, **kwargs):
    """
    Chỉ tạo profile khi user MỚI được tạo.
    Không chạy logic gì khi user được update để tránh recursion.
    
    Signal này được trigger bởi:
    - User registration
    - Google OAuth login (nếu user chưa tồn tại)
    """
    if created:
        # Chỉ tạo profile cho user mới, không check user cũ
        Profile.objects.get_or_create(user=instance)
        logger.info(f"Profile created for new user: {instance.email}")