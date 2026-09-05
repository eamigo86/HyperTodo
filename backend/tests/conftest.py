"""Shared pytest fixtures for HyperTodo."""

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
    """Create the primary test user."""
    return get_user_model().objects.create_user(
        username="ada", password="correct-horse"
    )


@pytest.fixture
def other_user(db):
    """Create a second user for isolation tests."""
    return get_user_model().objects.create_user(
        username="grace", password="correct-horse"
    )


@pytest.fixture
def admin_site():
    """Return Django's default admin site."""
    from django.contrib import admin

    return admin.site
