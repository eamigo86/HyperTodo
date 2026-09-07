"""URL configuration for HyperTodo."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("hv/", include("todo.urls")),
    # Returns [] unless DEBUG, so this is the development server only. Production
    # serves MEDIA_URL from the web server or object storage; see mobile/RELEASE.md.
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
