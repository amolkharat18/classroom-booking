from __future__ import annotations

from datetime import date

import pytest

from classroom_booking import auth
from classroom_booking import booking_service as service
from classroom_booking.db import connect, init_db


@pytest.fixture()
def conn():
    connection = connect(":memory:")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture()
def users(conn):
    admin_id = auth.create_user(conn, "admin", "secret", is_admin=True)
    user_id = auth.create_user(conn, "teacher", "secret", is_admin=False, actor_id=admin_id)
    return auth.get_user(conn, admin_id), auth.get_user(conn, user_id)


def test_password_hash_and_authentication(conn):
    auth.create_user(conn, "alice", "correct horse", is_admin=True)
    assert auth.authenticate(conn, "alice", "correct horse")["username"] == "alice"
    assert auth.authenticate(conn, "alice", "wrong") is None


def test_holiday_rejects_booking(conn, users):
    admin, teacher = users
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    service.upsert_holiday(conn, date(2026, 1, 26), "Republic Day", admin)
    with pytest.raises(ValueError, match="holidays"):
        service.create_booking(
            conn,
            room_id,
            teacher["id"],
            "Physics",
            "2026-01-26 10:00",
            "2026-01-26 11:00",
            teacher,
        )


def test_overlap_rejects_booking(conn, users):
    admin, teacher = users
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    service.create_booking(conn, room_id, teacher["id"], "Physics", "2026-02-02 10:00", "2026-02-02 11:00", teacher)
    with pytest.raises(ValueError, match="already booked"):
        service.create_booking(conn, room_id, teacher["id"], "Chemistry", "2026-02-02 10:30", "2026-02-02 11:30", teacher)


def test_daily_recurring_booking_generates_series(conn, users):
    admin, teacher = users
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    ids = service.create_booking(
        conn,
        room_id,
        teacher["id"],
        "Standup",
        "2026-02-02 09:00",
        "2026-02-02 09:30",
        teacher,
        {"frequency": "daily", "occurrence_count": 3},
    )
    assert len(ids) == 3
    bookings = service.list_bookings(conn, user_id=teacher["id"])
    assert len(bookings) == 3
    assert len({row["series_id"] for row in bookings}) == 1


def test_series_delete_cancels_all_occurrences(conn, users):
    admin, teacher = users
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    ids = service.create_booking(
        conn,
        room_id,
        teacher["id"],
        "Lab",
        "2026-03-02 12:00",
        "2026-03-02 13:00",
        teacher,
        {"frequency": "weekly", "occurrence_count": 4},
    )
    count = service.delete_booking(conn, ids[0], teacher, scope="series")
    assert count == 4
    assert service.list_bookings(conn, user_id=teacher["id"]) == []


def test_non_owner_cannot_delete_booking(conn, users):
    admin, teacher = users
    other_id = auth.create_user(conn, "other", "secret", actor_id=admin["id"])
    other = auth.get_user(conn, other_id)
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    ids = service.create_booking(conn, room_id, teacher["id"], "Math", "2026-04-01 10:00", "2026-04-01 11:00", teacher)
    with pytest.raises(PermissionError):
        service.delete_booking(conn, ids[0], other)


def test_default_weekends_reject_bookings(conn, users):
    admin, teacher = users
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    assert service.get_closed_weekdays(conn) == {5, 6}
    with pytest.raises(ValueError, match="closed days"):
        service.create_booking(
            conn,
            room_id,
            teacher["id"],
            "Weekend class",
            "2026-02-07 10:00",
            "2026-02-07 11:00",
            teacher,
        )


def test_admin_can_change_weekly_closed_days(conn, users):
    admin, teacher = users
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    service.set_closed_weekdays(conn, [6], admin)
    ids = service.create_booking(
        conn,
        room_id,
        teacher["id"],
        "Saturday class",
        "2026-02-07 10:00",
        "2026-02-07 11:00",
        teacher,
    )
    assert len(ids) == 1
    with pytest.raises(ValueError, match="closed days"):
        service.create_booking(
            conn,
            room_id,
            teacher["id"],
            "Sunday class",
            "2026-02-08 10:00",
            "2026-02-08 11:00",
            teacher,
        )

def test_admin_can_clear_weekly_closed_days(conn, users):
    admin, teacher = users
    room_id = service.create_room(conn, "Room A", 40, "Block 1", "#2563eb", admin)
    service.set_closed_weekdays(conn, [], admin)
    assert service.get_closed_weekdays(conn) == set()
    ids = service.create_booking(
        conn,
        room_id,
        teacher["id"],
        "Sunday class",
        "2026-02-08 10:00",
        "2026-02-08 11:00",
        teacher,
    )
    assert len(ids) == 1


def test_voice_agent_enabled_default_false(conn):
    assert service.get_voice_agent_enabled(conn) is False


def test_admin_can_toggle_voice_agent_setting(conn, users):
    admin, _ = users
    service.set_voice_agent_enabled(conn, False, admin)
    assert service.get_voice_agent_enabled(conn) is False
    service.set_voice_agent_enabled(conn, True, admin)
    assert service.get_voice_agent_enabled(conn) is True


def test_non_admin_cannot_toggle_voice_agent_setting(conn, users):
    _, teacher = users
    with pytest.raises(PermissionError):
        service.set_voice_agent_enabled(conn, False, teacher)