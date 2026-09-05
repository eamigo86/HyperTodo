"""Small helpers for environment-backed Django settings."""

import os


def csv_setting(name: str, default: str) -> list[str]:
    """Read a comma-separated environment setting.

    Args:
        name: Environment variable name.
        default: Value used when the variable is absent.

    Returns:
        Trimmed nonempty values in their configured order.
    """
    return [
        value.strip()
        for value in os.environ.get(name, default).split(",")
        if value.strip()
    ]
