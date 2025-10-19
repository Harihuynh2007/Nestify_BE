# auth_app/apps.py
from django.apps import AppConfig

class AuthAppConfig(AppConfig):
    name = 'auth_app'
    default_auto_field = 'django.db.models.BigAutoField'
    def ready(self):
        # import signals khi Django khởi động
        import auth_app.signals