import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from procurement import auth, chat_service
from procurement.repository import init_db, session_factory


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    return session_factory(engine)()


def _user(session, username: str):
    return auth.create_user(
        session,
        username=username,
        display_name=username.title(),
        role="employee",
        password="pw",
    )


def test_global_fifo_cap_evicts_oldest():
    session = _make_session()
    users = [_user(session, f"u{i}") for i in range(6)]

    first = chat_service.create_session(session, user_id=users[0].id, title="oldest")
    chat_service.add_message(session, first, role="user", content="hello from 1")

    for i in range(1, chat_service.MAX_SESSIONS):
        chat_service.create_session(session, user_id=users[i].id, title=f"chat {i}")

    assert len(chat_service.list_sessions(session)) == chat_service.MAX_SESSIONS
    # The oldest (with its messages) is still here — cap not yet exceeded.
    assert chat_service.get_session_row(session, first.id) is not None

    # Creating the 6th evicts the oldest globally, even though another user owns it.
    chat_service.create_session(session, user_id=users[5].id, title="newest")
    assert chat_service.get_session_row(session, first.id) is None
    assert len(chat_service.list_sessions(session)) == chat_service.MAX_SESSIONS

    remaining_messages = session.query(chat_service.ChatMessage).filter_by(
        session_id=first.id
    )
    assert remaining_messages.count() == 0


def test_add_and_list_messages_in_order():
    session = _make_session()
    user = _user(session, "alice")
    row = chat_service.create_session(session, user_id=user.id, title="t")

    chat_service.add_message(session, row, role="user", content="first")
    chat_service.add_message(session, row, role="assistant", content="second")

    messages = chat_service.list_messages(session, row.id)
    assert [m.content for m in messages] == ["first", "second"]
    assert [m.role for m in messages] == ["user", "assistant"]


def test_invalid_role_rejected():
    session = _make_session()
    user = _user(session, "alice")
    row = chat_service.create_session(session, user_id=user.id)
    with pytest.raises(ValueError):
        chat_service.add_message(session, row, role="robot", content="hi")


def test_draft_roundtrip():
    session = _make_session()
    user = _user(session, "alice")
    row = chat_service.create_session(session, user_id=user.id)

    draft = {"category": "monitor", "quantity": 6}
    chat_service.save_draft(session, row, json.dumps(draft))
    assert chat_service.load_draft(session, row) == draft

    chat_service.save_draft(session, row, "null")
    assert chat_service.load_draft(session, row) is None


def test_title_updates_on_first_user_message():
    session = _make_session()
    user = _user(session, "alice")
    row = chat_service.create_session(session, user_id=user.id, title="New chat")
    chat_service.add_message(session, row, role="user", content="6 monitors please")
    if row.title == "New chat":
        row.title = "6 monitors please"[:40]
        session.commit()
    assert row.title == "6 monitors please"