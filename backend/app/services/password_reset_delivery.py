from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import PasswordResetSettings


class PasswordResetDeliveryError(Exception):
    """Raised when a password-reset delivery provider cannot send."""


@dataclass(frozen=True)
class PasswordResetDeliveryResult:
    status: str
    delivered: bool


class PasswordResetDeliveryProvider(Protocol):
    def deliver(
        self,
        *,
        email: str,
        full_name: str,
        reset_url: str,
    ) -> PasswordResetDeliveryResult:
        ...


class NoopPasswordResetDeliveryProvider:
    """Default provider: no external I/O and no retained reset URL."""

    def deliver(
        self,
        *,
        email: str,
        full_name: str,
        reset_url: str,
    ) -> PasswordResetDeliveryResult:
        return PasswordResetDeliveryResult(status="not_sent", delivered=False)


class CapturePasswordResetDeliveryProvider:
    """Disposable local/test provider; captured URLs are process-local only."""

    def __init__(self) -> None:
        self.deliveries: list[dict[str, str]] = []

    def deliver(
        self,
        *,
        email: str,
        full_name: str,
        reset_url: str,
    ) -> PasswordResetDeliveryResult:
        self.deliveries.append(
            {"email": email, "full_name": full_name, "reset_url": reset_url}
        )
        return PasswordResetDeliveryResult(status="sent", delivered=True)


def get_password_reset_delivery_provider(
    settings: PasswordResetSettings,
) -> PasswordResetDeliveryProvider:
    if settings.email_provider_mode == "capture":
        return CapturePasswordResetDeliveryProvider()
    return NoopPasswordResetDeliveryProvider()
