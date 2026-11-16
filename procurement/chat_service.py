"""Chat persistence service.

Sessions and messages survive reruns and refreshes. The demo caps the store
at ``MAX_SESSIONS`` sessions **globally** (not per user): creating a new
session when the cap is reached deletes the oldest one, with its messages.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .repository import ChatMessage, ChatSession, Order

#: Global cap for the demo — new sessions overwrite the oldest.
MAX_SESSIONS = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(
    session: Session, *, user_id: int, title: str = "New chat"
) -> ChatSession:
    """Create a chat session, evicting the oldest one if the cap is hit."""
    all_sessions = list(
        session.scalars(
            select(ChatSession).order_by(ChatSession.created_at.desc())
        )
    )
    for old in all_sessions[MAX_SESSIONS - 1 :]:
        session.query(ChatMessage).filter(
            ChatMessage.session_id == old.id
        ).delete(synchronize_session=False)
        session.delete(old)

    row = ChatSession(
        user_id=user_id,
        title=title.strip() or "New chat",
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def list_sessions(session: Session) -> list[ChatSession]:
    stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
    return list(session.scalars(stmt))


def get_session_row(session: Session, session_id: int) -> ChatSession | None:
    return session.get(ChatSession, session_id)


def touch(session: Session, row: ChatSession) -> None:
    row.updated_at = _now()
    session.commit()


def add_message(
    session: Session, row: ChatSession, *, role: str, content: str
) -> ChatMessage:
    if role not in ("user", "assistant"):
        raise ValueError(f"invalid chat role {role!r}")
    message = ChatMessage(
        session_id=row.id, role=role, content=content, created_at=_now()
    )
    session.add(message)
    session.flush()
    row.updated_at = _now()
    session.commit()
    session.refresh(message)
    return message


def list_messages(session: Session, chat_session_id: int) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == chat_session_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    return list(session.scalars(stmt))


def save_draft(session: Session, row: ChatSession, draft_json: str) -> None:
    """Persist the current RequestDraft snapshot for the session."""
    row.draft_json = draft_json
    row.updated_at = _now()
    session.commit()


def load_draft(session: Session, row: ChatSession) -> dict | None:
    if not row.draft_json:
        return None
    try:
        return json.loads(row.draft_json)
    except json.JSONDecodeError:
        return None


def link_order(session: Session, row: ChatSession, order_id: int) -> None:
    row.order_id = order_id
    row.updated_at = _now()
    session.commit()


def linked_order(session: Session, row: ChatSession) -> Order | None:
    return session.get(Order, row.order_id) if row.order_id else None


def delete_session(session: Session, row: ChatSession) -> None:
    session.query(ChatMessage).filter(
        ChatMessage.session_id == row.id
    ).delete(synchronize_session=False)
    session.delete(row)
    session.commit()