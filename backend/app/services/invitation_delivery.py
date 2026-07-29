from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import InvitationSettings


@dataclass(frozen=True)
class InvitationDeliveryResult:
    status: str
    delivered: bool


class InvitationDeliveryProvider(Protocol):
    def deliver(self, *, email: str, full_name: str, activation_url: str) -> InvitationDeliveryResult: ...


class NoopInvitationDeliveryProvider:
    """Development-safe provider that performs no external I/O and retains no URL."""

    def deliver(self, *, email: str, full_name: str, activation_url: str) -> InvitationDeliveryResult:
        return InvitationDeliveryResult(status="not_sent", delivered=False)


class CaptureInvitationDeliveryProvider:
    """Explicit local/test provider; captured URLs exist only in process memory."""

    def __init__(self) -> None:
        self.deliveries: list[dict[str, str]] = []

    def deliver(self, *, email: str, full_name: str, activation_url: str) -> InvitationDeliveryResult:
        self.deliveries.append({"email": email, "full_name": full_name, "activation_url": activation_url})
        return InvitationDeliveryResult(status="sent", delivered=True)


def get_invitation_delivery_provider(settings: InvitationSettings) -> InvitationDeliveryProvider:
    if settings.email_provider_mode == "capture":
        return CaptureInvitationDeliveryProvider()
    return NoopInvitationDeliveryProvider()
