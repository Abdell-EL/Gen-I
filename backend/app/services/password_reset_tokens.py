from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import PasswordResetToken

def invalidate_outstanding_password_reset_tokens(db: Session, user_id: int, *, now: datetime | None = None) -> None:
    """Mutate unused reset-token rows only; transaction owner commits or rolls back."""
    timestamp = now or datetime.now(timezone.utc)
    for token in db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user_id, PasswordResetToken.consumed_at.is_(None), PasswordResetToken.invalidated_at.is_(None)).with_for_update()).scalars():
        token.invalidated_at = timestamp
