"""Typed schema declarations owned by the existing HyperTodo mobile host."""

from typing import Any


def schema_extensions() -> dict[str, Any]:
    """Return detached declarations for application behaviors and attributes.

    Returns:
        Fresh typed declarations for the application custom behaviors and image variant.
        The package provides automatic standard validation; these declarations do
        not select a schema, enable validation, or install mobile behaviors.
    """
    return {
        "BEHAVIORS": {
            "notify-resources": {
                "ATTRIBUTES": {
                    "resources": {
                        "TYPE": "string",
                        "REQUIRED": True,
                        "ENUM": [
                            "tasks",
                            "categories",
                            "ui",
                            "tasks categories",
                            "tasks ui",
                            "categories ui",
                            "tasks categories ui",
                        ],
                    },
                },
            },
            "show-snackbar": {
                "ATTRIBUTES": {
                    "message": {"TYPE": "string"},
                    "tone": {"TYPE": "string", "ENUM": ["success", "error"]},
                }
            },
            "store-biometric-token": {"ATTRIBUTES": {"token": {"TYPE": "string"}}},
            "probe-biometrics": {
                "ATTRIBUTES": {
                    "available-target": {"TYPE": "string"},
                    "token-target": {"TYPE": "string"},
                }
            },
            "biometric-unlock": {"ATTRIBUTES": {"prompt": {"TYPE": "string"}}},
            "pick-avatar": {
                "ATTRIBUTES": {
                    "preview-target": {"TYPE": "string"},
                    "current-target": {"TYPE": "string"},
                }
            },
        },
        "ELEMENT_ATTRIBUTES": {
            "picker-item": {
                "realtime-entity-key": {"TYPE": "string"},
                "realtime-entity-epoch": {"TYPE": "string"},
            },
            "image": {"variant": {"TYPE": "string", "ENUM": ["face", "fingerprint"]}},
        },
    }
