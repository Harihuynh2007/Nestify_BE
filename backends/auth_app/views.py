# auth_app/views.py - Updated MeProfileView
from django.contrib.auth import authenticate, login, logout, get_user_model
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken
import requests
from boards.models import Workspace
from django.core.files.base import ContentFile
import traceback
from django.db.models import Q
from django.conf import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import logging

logger = logging.getLogger(__name__)

from .models import Profile

from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserSerializer,
    GoogleLoginSerializer,
    ProfileSerializer,
    UserAvatarSerializer,
)

User = get_user_model()

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

# ... Giữ nguyên các views khác ...

class MeProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        return Response(ProfileSerializer(profile, context={"request": request}).data)

    def patch(self, request):
        profile = request.user.profile
        
        try:
            # Handle FormData from frontend
            data = request.data.copy()
            
            # Clean up FormData values - frontend có thể gửi string thay vì boolean
            boolean_fields = ['is_discoverable', 'show_boards_on_profile']
            for field in boolean_fields:
                if field in data:
                    value = data[field]
                    if isinstance(value, str):
                        # Convert string to boolean
                        data[field] = value.lower() in ('true', '1', 'on', 'yes')
                    elif value is None:
                        data[field] = False
            
            # Clean up text fields
            text_fields = ['display_name', 'bio']
            for field in text_fields:
                if field in data and data[field] is None:
                    data[field] = ""
            
            # Debug log (remove in production)
            print(f"Received data: {dict(data)}")
            
            serializer = ProfileSerializer(profile, data=data, partial=True, context={"request": request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            
            # Return updated data
            return Response(ProfileSerializer(profile, context={"request": request}).data)
            
        except Exception as e:
            print(f"Profile update error: {e}")
            traceback.print_exc()
            return Response(
                {"error": f"Profile update failed: {str(e)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

# Các views khác giữ nguyên...
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save() 

        tokens = get_tokens_for_user(user)
        logger.info(f"New user registered: {user.email}")
        return Response({
            "ok": True,
            "user": UserSerializer(user, context={"request": request}).data,
            "token": tokens["access"],
            "refresh": tokens["refresh"]
        }, status=status.HTTP_201_CREATED)

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        login(request, user)
        tokens = get_tokens_for_user(user)

        if not Workspace.objects.filter(owner=user).exists():
            Workspace.objects.create(name="Hard Spirit", owner=user)

        return Response({
            "ok": True,
            "user": UserSerializer(user, context={"request": request}).data, 
            "token": tokens["access"],
            "refresh": tokens["refresh"]
        })

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        logout(request)
        logger.info(f"User logged out: {request.user.email}")
        return Response({"ok": True, "message": "Logged out successfully."})

class MeView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data)

class GoogleLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        input_serializer = GoogleLoginSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        token = input_serializer.validated_data['token']

        try:
            id_info = id_token.verify_oauth2_token(
                token, 
                google_requests.Request(), 
                settings.GOOGLE_OAUTH2_CLIENT_ID # Lấy Client ID từ file settings.py
            )

            # Lấy email từ kết quả đã được xác thực
            email = id_info.get('email')

            if not email:
                return Response({'error': 'No email in token'}, status=status.HTTP_400_BAD_REQUEST)

            try:
                user = User.objects.get(email=email)
                created = False
            except User.DoesNotExist:
                user = User.objects.create_user(username=email, email=email)
                created = True

            profile, _ = Profile.objects.get_or_create(user=user)

            login(request, user)
            tokens = get_tokens_for_user(user)

            picture = id_info.get('picture')

            if picture and (created or not profile.avatar):
                try:
                    resp_img = requests.get(picture, timeout=5)
                    resp_img.raise_for_status()
                    fname = f'user_{user.id}.jpg'
                    profile.avatar.save(fname, ContentFile(resp_img.content), save=True)
                except Exception as e:
                    print(f"Failed to fetch Google avatar for {email}: {e}")

            user_data = UserSerializer(user, context={'request': request}).data
            if not Workspace.objects.filter(owner=user).exists():
                Workspace.objects.create(name="Hard Spirit", owner=user)
            return Response({
                'ok': True,
                'user': user_data,
                'token': tokens['access'],
                'refresh': tokens['refresh'],
            })

        except requests.exceptions.HTTPError as e:
            print('[GoogleLogin] HTTP Error:', str(e))
            return Response({'error': 'Invalid or expired Google token.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print('[GoogleLogin] General Exception:', str(e))
            traceback.print_exc()
            return Response({'error': 'An internal server error occurred.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
class UserSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.query_params.get('q', '')
        if len(query) < 2:
            return Response([], status=status.HTTP_200_OK)

        users = User.objects.filter(
            Q(username__icontains=query) | Q(email__icontains=query)
        )[:10]

        # Use UserAvatarSerializer for search results
        serializer = UserAvatarSerializer([u.profile for u in users], many=True, context={'request': request})
        return Response(serializer.data)