"""URL configuration for HyperTodo."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from todo.realtime_views import events

# Hyperview-aware answers for an unknown URL and an unhandled exception: an HTML page
# is something the mobile client cannot parse. Anything outside the API keeps Django's
# own page, and DEBUG keeps its technical pages, which Django renders without a handler.
handler404 = "todo.views.not_found"
handler500 = "todo.views.server_error"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("hv/", include("todo.urls")),
    path("realtime/events/", events, name="realtime-events"),
    # Returns [] unless DEBUG, so this is the development server only. Production
    # serves MEDIA_URL from the web server or object storage; see mobile/RELEASE.md.
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
