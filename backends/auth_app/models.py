from django.db import models, transaction
from django.conf import settings
import uuid
from PIL import Image
import io
from django.core.files.base import ContentFile
import logging

logger = logging.getLogger(__name__)

def avatar_upload_to(instance, filename):
    """Generate unique avatar path: avatars/user_{id}/{uuid}.{ext}"""
    ext = filename.split('.')[-1].lower()
    new_filename = f'{uuid.uuid4()}.{ext}'
    return f'avatars/user_{instance.user.id}/{new_filename}'

def banner_upload_to(instance, filename):
    """Generate unique banner path: banners/user_{id}/{uuid}.{ext}"""
    ext = filename.split('.')[-1].lower()
    new_filename = f'{uuid.uuid4()}.{ext}'
    return f'banners/user_{instance.user.id}/{new_filename}'

class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    
    # Avatar fields
    avatar = models.ImageField(
        upload_to=avatar_upload_to,
        blank=True,
        null=True,
        help_text="User avatar image"
    )
    avatar_thumbnail = models.ImageField(
        upload_to=avatar_upload_to,
        blank=True,
        null=True,
        help_text="Thumbnail version (40x40) for cards/members"
    )
    
    # Banner field
    banner = models.ImageField(
        upload_to=banner_upload_to,
        blank=True,
        null=True,
        help_text="Profile banner image"
    )
    
    # Profile info
    display_name = models.CharField(max_length=50, blank=True, db_index=True)  # Added index
    bio = models.TextField(blank=True, default="")
    
    # Privacy settings
    is_discoverable = models.BooleanField(default=True, db_index=True)  # Added index
    show_boards_on_profile = models.BooleanField(default=False)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_profiles'
        indexes = [
            models.Index(fields=['display_name']),  # For search queries
            models.Index(fields=['is_discoverable']),  # For filtering
        ]
        
    def __str__(self):
        return f"Profile<{self.user.email}:{self.get_display_name()}>"
    
    def get_display_name(self) -> str:
        """
        Trả về tên hiển thị tốt nhất theo thứ tự ưu tiên:
        1. display_name (nếu có và không empty)
        2. user.first_name (nếu có)
        3. email username part
        """
        if self.display_name:
            cleaned = ' '.join(self.display_name.strip().split())
            if cleaned:
                return cleaned
        
        if hasattr(self.user, 'first_name') and self.user.first_name:
            cleaned = ' '.join(self.user.first_name.strip().split())
            if cleaned:
                return cleaned
                
        return self.user.email.split('@')[0].strip()
    
    def get_initials(self) -> str:
        """
        Trả về initials (2 ký tự) để hiển thị khi không có avatar.
        
        Logic:
        - "John Doe" → "JD"
        - "John" → "JO"
        - "J" → "JJ"
        - Invalid → "U"
        """
        name = self.get_display_name()
        parts = name.strip().split()
        
        if len(parts) >= 2:
            # First and last name initials
            first_char = parts[0][0] if parts[0] else ''
            last_char = parts[-1][0] if parts[-1] else ''
            initials = f"{first_char}{last_char}"
        elif len(parts) == 1 and len(parts[0]) >= 2:
            # Single word: take first 2 chars
            initials = parts[0][:2]
        elif len(parts) == 1 and len(parts[0]) == 1:
            # Single char: duplicate it
            initials = f"{parts[0]}{parts[0]}"
        else:
            return "U"  # Ultimate fallback
        
        # Safe upper() for Unicode - handle exceptions
        try:
            return initials.upper()
        except:
            return initials[:2].upper() if len(initials) >= 2 else "U"
    
    def save(self, *args, **kwargs):
        """
        Override save để:
        1. Xóa old avatar/thumbnail khi upload mới
        2. Tạo thumbnail tự động
        3. Đảm bảo transaction safety
        """
        # Track if avatar changed bằng cách check field name thay vì compare file
        avatar_changed = False
        old_avatar = None
        old_thumbnail = None
        
        if self.pk:
            try:
                old_instance = Profile.objects.only('avatar', 'avatar_thumbnail').get(pk=self.pk)
                # Check if avatar field name changed (more reliable than file comparison)
                if old_instance.avatar.name != self.avatar.name:
                    avatar_changed = True
                    old_avatar = old_instance.avatar
                    old_thumbnail = old_instance.avatar_thumbnail
            except Profile.DoesNotExist:
                avatar_changed = bool(self.avatar)
        else:
            # New instance
            avatar_changed = bool(self.avatar)
        
        # Save trong transaction để đảm bảo consistency
        with transaction.atomic():
            super().save(*args, **kwargs)
            
            # Tạo thumbnail nếu avatar thay đổi
            if avatar_changed and self.avatar:
                self._create_thumbnail()
            
        # Xóa old files SAU KHI save thành công (ngoài transaction)
        # Tránh race condition và đảm bảo new files đã được lưu
        if old_avatar:
            try:
                old_avatar.delete(save=False)
            except Exception as e:
                logger.warning(f"Failed to delete old avatar for user {self.user_id}: {e}")
        
        if old_thumbnail:
            try:
                old_thumbnail.delete(save=False)
            except Exception as e:
                logger.warning(f"Failed to delete old thumbnail for user {self.user_id}: {e}")
    
    def _create_thumbnail(self):
        """
        Tạo thumbnail 40x40 từ avatar.
        Chạy synchronously trong save() - có thể chuyển sang Celery task sau.
        
        Process:
        1. Open avatar file (support cloud storage)
        2. Convert to RGB (handle transparency)
        3. Crop to square from center
        4. Resize to 40x40
        5. Save as JPEG (optimized)
        """
        try:
            with self.avatar.open('rb') as avatar_file:
                image = Image.open(avatar_file)
                
                # Convert to RGB for consistent JPEG output
                if image.mode in ('RGBA', 'LA', 'P'):
                    rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                    if image.mode == 'P':
                        image = image.convert('RGBA')
                    if image.mode == 'RGBA':
                        rgb_image.paste(image, mask=image.split()[-1])
                    else:
                        rgb_image.paste(image)
                    image = rgb_image
                
                # Make square crop from center
                image = self._make_square_crop(image)
                
                # Resize to thumbnail
                thumbnail_size = (40, 40)
                image.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
                
                # Save as JPEG
                thumb_io = io.BytesIO()
                image.save(thumb_io, format='JPEG', quality=85, optimize=True)
                thumb_io.seek(0)
                
                # Generate unique filename
                thumb_filename = f"thumb_{uuid.uuid4()}.jpg"
                
                # Save thumbnail without triggering another save()
                self.avatar_thumbnail.save(
                    thumb_filename,
                    ContentFile(thumb_io.read()),
                    save=False
                )
                
                # Direct DB update to avoid recursion
                Profile.objects.filter(pk=self.pk).update(
                    avatar_thumbnail=self.avatar_thumbnail.name
                )
                
                logger.info(f"Thumbnail created for user {self.user_id}")
                
        except Exception as e:
            logger.error(f"Thumbnail creation failed for user {self.user_id}: {e}")
            # Don't raise - thumbnail is not critical, profile should still save
    
    def _make_square_crop(self, image):
        """Crop image to square from center"""
        width, height = image.size
        
        if width == height:
            return image
        
        # Calculate center square crop box
        size = min(width, height)
        left = (width - size) // 2
        top = (height - size) // 2
        right = left + size
        bottom = top + size
        
        return image.crop((left, top, right, bottom))