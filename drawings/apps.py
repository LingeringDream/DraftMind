from django.apps import AppConfig


class DrawingsConfig(AppConfig):
    """图纸解析应用配置。"""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'drawings'
    verbose_name = '图纸管理'
