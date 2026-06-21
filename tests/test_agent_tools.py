from __future__ import annotations

from classroom_booking import agent
from classroom_booking import auth
from classroom_booking import booking_service as service
from classroom_booking.db import connect, init_db


def test_agent_tool_check_and_create_booking():
    conn = connect(":memory:")
    init_db(conn)
    admin_id = auth.create_user(conn, "admin", "secret", is_admin=True)
    admin = auth.get_user(conn, admin_id)
    service.create_room(conn, "Room A", 20, "", "#2563eb", admin)

    availability = agent.execute_tool(
        conn,
        admin,
        "check_availability",
        {"room_name": "Room A", "start": "2026-05-01 10:00", "end": "2026-05-01 11:00"},
    )
    assert availability["availability"][0]["available"] is True

    created = agent.execute_tool(
        conn,
        admin,
        "create_booking",
        {
            "room_name": "Room A",
            "title": "Demo",
            "start": "2026-05-01 10:00",
            "end": "2026-05-01 11:00",
        },
    )
    assert len(created["created_booking_ids"]) == 1

    availability = agent.execute_tool(
        conn,
        admin,
        "check_availability",
        {"room_name": "Room A", "start": "2026-05-01 10:00", "end": "2026-05-01 11:00"},
    )
    assert availability["availability"][0]["available"] is False
