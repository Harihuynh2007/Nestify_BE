from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Profile

User = get_user_model()

# Lightweight serializer cho avatar display trong cards/members
class UserAvatarSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer cho avatar display.
    Dùng trong: card members, board members, search results.
    """
    id = serializers.IntegerField(source='user.id', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    display_name = serializers.SerializerMethodField()
    initials = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    avatar_thumbnail_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Profile
        fields = ['id', 'email', 'display_name', 'initials', 'avatar_url', 'avatar_thumbnail_url']
    
    def get_display_name(self, profile):
        return profile.get_display_name()
    
    def get_initials(self, profile):
        return profile.get_initials()
    
    def get_avatar_url(self, profile):
        request = self.context.get('request')
        if profile.avatar and request:
            return request.build_absolute_uri(profile.avatar.url)
        return None
    
    def get_avatar_thumbnail_url(self, profile):
        request = self.context.get('request')
        if profile.avatar_thumbnail and request:
            return request.build_absolute_uri(profile.avatar_thumbnail.url)
        return None


class ProfileSerializer(serializers.ModelSerializer):
    """
    Full profile serializer cho settings page.
    Support: avatar/banner upload, privacy settings, profile info.
    """
    # Read-only computed fields
    avatar_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField() 
    display_name_computed = serializers.SerializerMethodField()
    initials = serializers.SerializerMethodField()
    
    # Write-only upload fields
    avatar = serializers.ImageField(write_only=True, required=False)
    banner = serializers.ImageField(write_only=True, required=False)
    
    class Meta:
        model = Profile
        fields = [
            'display_name', 'bio', 'is_discoverable', 'show_boards_on_profile',
            'avatar', 'banner', 'avatar_url', 'banner_url', 
            'display_name_computed', 'initials'
        ]
    
    def validate_avatar(self, value):
        """
        Validate avatar upload:
        - Max size: 5MB
        - Allowed types: JPEG, PNG, GIF, WebP
        - Min dimensions: 40x40 (để tạo thumbnail)
        """
        if value:
            # Check file size (5MB limit)
            max_size = 5 * 1024 * 1024  # 5MB
            if value.size > max_size:
                raise serializers.ValidationError(
                    f"Avatar file too large. Maximum size is 5MB. Your file is {value.size / 1024 / 1024:.1f}MB."
                )
            
            # Check file type
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
            if value.content_type not in allowed_types:
                raise serializers.ValidationError(
                    f"Invalid file type. Allowed types: JPEG, PNG, GIF, WebP."
                )
            
            # Check image dimensions (optional - ensure it's a valid image)
            try:
                from PIL import Image
                image = Image.open(value)
                width, height = image.size
                
                if width < 40 or height < 40:
                    raise serializers.ValidationError(
                        "Image too small. Minimum size is 40x40 pixels."
                    )
                
                # Reset file pointer after reading
                value.seek(0)
            except Exception as e:
                raise serializers.ValidationError(f"Invalid image file: {str(e)}")
        
        return value
    
    def validate_banner(self, value):
        """
        Validate banner upload:
        - Max size: 10MB (banner có thể lớn hơn avatar)
        - Allowed types: JPEG, PNG, GIF, WebP
        """
        if value:
            # Check file size (10MB limit)
            max_size = 10 * 1024 * 1024  # 10MB
            if value.size > max_size:
                raise serializers.ValidationError(
                    f"Banner file too large. Maximum size is 10MB. Your file is {value.size / 1024 / 1024:.1f}MB."
                )
            
            # Check file type
            allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
            if value.content_type not in allowed_types:
                raise serializers.ValidationError(
                    f"Invalid file type. Allowed types: JPEG, PNG, GIF, WebP."
                )
        
        return value
    
    def validate_display_name(self, value):
        """Validate display name length and characters"""
        if value:
            cleaned = value.strip()
            if len(cleaned) > 50:
                raise serializers.ValidationError("Display name too long (max 50 characters).")
        return value
    
    def validate_bio(self, value):
        """Validate bio length"""
        if value and len(value) > 500:
            raise serializers.ValidationError("Bio too long (max 500 characters).")
        return value
    
    def validate(self, data):
        """
        Custom validation to handle data type conversions.
        Frontend có thể gửi string thay vì boolean qua FormData.
        """
        # Ensure boolean fields are properly typed
        boolean_fields = ['is_discoverable', 'show_boards_on_profile']
        for field in boolean_fields:
            if field in data:
                value = data[field]
                if isinstance(value, str):
                    # Convert string to boolean
                    data[field] = value.lower() in ('true', '1', 'yes', 'on')
                elif value is None:
                    data[field] = False
        
        return data
    
    def get_avatar_url(self, profile):
        request = self.context.get('request')
        if profile.avatar and request:
            return request.build_absolute_uri(profile.avatar.url)
        return None
        
    def get_banner_url(self, profile):
        request = self.context.get('request')
        if profile.banner and request:
            return request.build_absolute_uri(profile.banner.url)
        return None
    
    def get_display_name_computed(self, profile):
        return profile.get_display_name()
    
    def get_initials(self, profile):
        return profile.get_initials()


class UserSerializer(serializers.ModelSerializer):
    """
    Enhanced user serializer với profile info.
    Dùng trong: /auth/me/, login/register responses.
    """
    profile = ProfileSerializer(read_only=True)
    role = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'profile', 'role')

    def get_role(self, user):
        """Xác định vai trò: admin hoặc user"""
        return "admin" if user.is_superuser else "user"


class RegisterSerializer(serializers.ModelSerializer):
    """
    Serializer cho user registration.
    Validate email uniqueness và password strength.
    """
    password = serializers.CharField(
        write_only=True,
        required=True,
        min_length=8,
        error_messages={
            "min_length": "Password must be at least 8 characters."
        }
    )

    class Meta:
        model = User
        fields = ('email', 'password')

    def validate_email(self, value):
        """
        Check email uniqueness.
        Note: Đây là potential security issue (user enumeration).
        Consider generic message trong production.
        """
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already registered.")
        return value

    def create(self, validated_data):
        """
        Tạo user mới với hashed password.
        Signal sẽ tự động tạo Profile.
        """
        user = User.objects.create_user(
            username=validated_data['email'],  # Use email as username
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user


class LoginSerializer(serializers.Serializer):
    """
    Serializer cho login.
    Support cả email và username login.
    """
    email = serializers.CharField(label="Email/Username", write_only=True)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        """
        Authenticate user với email hoặc username.
        """
        email_or_username = data.get('email')
        password = data.get('password')

        if not email_or_username or not password:
            raise serializers.ValidationError(
                "Both email/username and password are required.",
                code='authorization'
            )

        # Try to find user by email first
        try:
            user_obj = User.objects.get(email=email_or_username)
            username = user_obj.username
        except User.DoesNotExist:
            # If not found, assume it's a username
            username = email_or_username

        user = authenticate(username=username, password=password)

        if not user:
            raise serializers.ValidationError(
                "Invalid email/username or password.",
                code='authorization'
            )

        data['user'] = user
        return data


class GoogleLoginSerializer(serializers.Serializer):
    """Serializer để validate Google OAuth token"""
    token = serializers.CharField(write_only=True, required=True)