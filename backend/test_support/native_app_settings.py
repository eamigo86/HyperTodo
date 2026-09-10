"""Explicit private settings for a temporary native fixture, never defaults."""

from config import settings as base

from .native_app_fixture import load_fixture, settings_overrides

globals().update({key: value for key, value in vars(base).items() if key.isupper()})
globals().update(settings_overrides(load_fixture()))
HYPERVIEW = {**base.HYPERVIEW, "REALTIME": None}
HYPERVIEW.pop("CACHE", None)
