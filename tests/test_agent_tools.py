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


def test_capacity_aware_availability_and_suggestions():
    conn = connect(":memory:")
    init_db(conn)
    admin_id = auth.create_user(conn, "admin", "secret", is_admin=True)
    admin = auth.get_user(conn, admin_id)
    service.create_room(conn, "Room A", 20, "1st floor", "#2563eb", admin)
    service.create_room(conn, "Room B", 30, "2nd floor", "#10b981", admin)
    service.create_room(conn, "Room C", 8, "1st floor", "#f59e0b", admin)
    agent.execute_tool(
        conn,
        admin,
        "create_booking",
        {
            "room_name": "Room B",
            "title": "Booked",
            "start": "2026-07-20 10:00",
            "end": "2026-07-20 11:00",
        },
    )

    availability = agent.execute_tool(
        conn,
        admin,
        "check_availability",
        {"start": "2026-07-20 10:00", "end": "2026-07-20 11:00", "min_capacity": 10},
    )
    rooms = availability["availability"]
    assert all(room["capacity"] >= 10 for room in rooms)
    assert any(room["room_name"] == "Room A" for room in rooms)
    assert all(room["room_name"] != "Room C" for room in rooms)

    suggestions = agent.execute_tool(
        conn,
        admin,
        "suggest_rooms",
        {"start": "2026-07-20 10:00", "end": "2026-07-20 11:00", "min_capacity": 10},
    )
    assert suggestions["suggested_rooms"] == [
        {
            "room_id": rooms[0]["room_id"],
            "room_name": "Room A",
            "capacity": 20,
            "location": "1st floor",
            "available": True,
            "conflicts": [],
        }
    ]

    room_info = agent.execute_tool(
        conn,
        admin,
        "get_room_info",
        {"room_name": "Room A"},
    )
    assert room_info["room_name"] == "Room A"
    assert room_info["capacity"] == 20
