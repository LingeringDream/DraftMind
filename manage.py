#!/usr/bin/env python
"""Django 管理命令入口。

用法:
    python manage.py migrate          # 执行数据库迁移
    python manage.py runserver 5000   # 启动开发服务器
    python manage.py createsuperuser  # 创建管理员账户
"""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'draftmind_backend.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
