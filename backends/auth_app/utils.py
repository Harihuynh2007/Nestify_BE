# auth_app/utils.py
from PIL import Image
import io
from django.core.files.base import ContentFile
import uuid
import logging

logger = logging.getLogger(__name__)

def create_avatar_thumbnail(profile_instance):
    """
    Create thumbnail for avatar - can be called asynchronously
    Returns True if successful, False otherwise
    """
    if not profile_instance.avatar:
        return False
        
    try:
        with profile_instance.avatar.open('rb') as avatar_file:
            image = Image.open(avatar_file)
            
            # Convert to RGB for consistent JPEG output
            if image.mode in ('RGBA', 'LA', 'P'):
                # Create white background for transparency
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                
                # Paste with proper alpha handling
                if image.mode == 'RGBA':
                    rgb_image.paste(image, mask=image.split()[-1])
                else:
                    rgb_image.paste(image)
                image = rgb_image
            
            # Make square crop from center
            image = make_square_crop(image)
            
            # Create thumbnail
            thumbnail_size = (40, 40)
            image.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
            
            # Save as JPEG
            thumb_io = io.BytesIO()
            image.save(thumb_io, format='JPEG', quality=85, optimize=True)
            thumb_io.seek(0)
            
            # Generate unique filename
            thumb_filename = f"thumb_{uuid.uuid4()}.jpg"
            
            # Save thumbnail (without triggering save)
            profile_instance.avatar_thumbnail.save(
                thumb_filename,
                ContentFile(thumb_io.read()),
                save=False
            )
            
            # Update only thumbnail field in DB to avoid recursion
            from .models import Profile
            Profile.objects.filter(pk=profile_instance.pk).update(
                avatar_thumbnail=profile_instance.avatar_thumbnail.name
            )
            
            return True
            
    except Exception as e:
        logger.error(f"Thumbnail creation failed for user {profile_instance.user_id}: {e}")
        return False

def make_square_crop(image):
    """Crop image to square from center"""
    width, height = image.size
    
    if width == height:
        return image
    
    # Calculate crop box for center square
    size = min(width, height)
    left = (width - size) // 2
    top = (height - size) // 2
    right = left + size
    bottom = top + size
    
    return image.crop((left, top, right, bottom))

