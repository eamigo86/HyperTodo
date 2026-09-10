"""Conventional ASGI entry point for HyperTodo."""

import os

from dj_hyperview.realtime import realtime_asgi
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = realtime_asgi(get_asgi_application())
if settings.DEBUG:
    # Development only. Real API/SSE requests still enter the scope-owned app.
    application = ASGIStaticFilesHandler(application)
