"""HXML URL routes for the TODO application."""

from django.urls import path

from . import views

app_name = "todo"
urlpatterns = [
    path("", views.root, name="root"),
    path("source-probe/", views.source_probe, name="source-probe"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("biometric/login/", views.biometric_login, name="biometric-login"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("preferences/", views.preferences, name="preferences"),
    path("menu/", views.menu, name="menu"),
    path("menu/close/", views.menu_close, name="menu-close"),
    path("tasks/", views.task_list, name="tasks"),
    path("tasks/new/", views.task_new, name="task-new"),
    path("tasks/<uuid:task_id>/edit/", views.task_edit, name="task-edit"),
    path("tasks/<uuid:task_id>/toggle/", views.task_toggle, name="task-toggle"),
    path("tasks/<uuid:task_id>/delete/", views.task_delete, name="task-delete"),
    path("categories/", views.category_list, name="categories"),
    path("categories/new/", views.category_new, name="category-new"),
    path(
        "categories/<uuid:category_id>/edit/", views.category_edit, name="category-edit"
    ),
    path(
        "categories/<uuid:category_id>/delete/",
        views.category_delete,
        name="category-delete",
    ),
]
