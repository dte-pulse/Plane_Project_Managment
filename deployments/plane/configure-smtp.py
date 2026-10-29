"""Sync the SMTP environment into Plane's encrypted instance configuration."""

import os

from plane.license.models import InstanceConfiguration
from plane.license.utils.encryption import encrypt_data


smtp_settings = [
    ("ENABLE_SMTP", False),
    ("EMAIL_HOST", False),
    ("EMAIL_HOST_USER", False),
    ("EMAIL_HOST_PASSWORD", True),
    ("EMAIL_PORT", False),
    ("EMAIL_FROM", False),
    ("EMAIL_USE_TLS", False),
    ("EMAIL_USE_SSL", False),
]

if os.environ.get("ENABLE_SMTP") != "1":
    raise RuntimeError("Set ENABLE_SMTP=1 in the private API environment before syncing SMTP settings.")

for key, is_encrypted in smtp_settings:
    value = os.environ.get(key, "")
    if not value:
        raise RuntimeError(f"Required SMTP setting {key} is empty.")

    InstanceConfiguration.objects.update_or_create(
        key=key,
        defaults={
            "category": "SMTP",
            "is_encrypted": is_encrypted,
            "value": encrypt_data(value) if is_encrypted else value,
        },
    )

print("SMTP instance settings synced; password value was not displayed.")
