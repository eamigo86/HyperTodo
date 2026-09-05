"""URL configuration for HyperTodo."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("hv/", include("todo.urls")),
]
