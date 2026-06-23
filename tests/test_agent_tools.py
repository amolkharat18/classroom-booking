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


def test_format_tool_confirmation_message_plain_english():
    prompt = agent.format_tool_confirmation_message(
        "update_booking",
        {
            "booking_id": 42,
            "room_name": "Room A",
            "start": "2026-06-01 09:00",
            "end": "2026-06-01 10:00",
            "scope": "single",
        },
    )
    assert "I can update booking booking #42" in prompt
    assert "room 'Room A'" in prompt
    assert "Reply `confirm` to proceed." in prompt


def test_format_action_result_plain_english():
    assert agent.format_action_result({"updated_count": 1}) == "Confirmed. Updated 1 booking."
    assert agent.format_action_result({"deleted_count": 2}) == "Confirmed. Deleted 2 bookings."
    assert agent.format_action_result({"created_booking_ids": [1]}) == "Confirmed. Created 1 booking, ID 1. Please note it down for future modification or deletion."
    assert agent.format_action_result({"created_booking_ids": [1, 2]}) == "Confirmed. Created 2 bookings, IDs 1, 2. Please note them down for future modification or deletion."


def test_format_created_bookings_message_single_and_multiple():
    assert agent.format_created_bookings_message([123]) == (
        "Your new booking ID is 123. Please note it down for future modification or deletion."
    )
    assert agent.format_created_bookings_message([123, 456]) == (
        "Your new booking IDs are 123, 456. Please note them down for future modification or deletion."
    )


def test_prepare_update_confirmation_requests_only_required_details():
    conn = connect(":memory:")
    init_db(conn)
    admin_id = auth.create_user(conn, "admin", "secret", is_admin=True)
    admin = auth.get_user(conn, admin_id)
    service.create_room(conn, "Room A", 20, "", "#2563eb", admin)

    created = agent.execute_tool(
        conn,
        admin,
        "create_booking",
        {
            "room_name": "Room A",
            "title": "Kafka Session",
            "start": "2026-07-10 10:00",
            "end": "2026-07-10 11:00",
        },
    )
    booking_id = created["created_booking_ids"][0]

    result = agent._prepare_update_confirmation(conn, admin, {"booking_id": booking_id})
    assert result.pending_tool is None
    assert "I found booking" in result.message
    assert "Tell me what to change" in result.message


def test_prepare_update_confirmation_checks_conflicts_before_confirm():
    conn = connect(":memory:")
    init_db(conn)
    admin_id = auth.create_user(conn, "admin", "secret", is_admin=True)
    admin = auth.get_user(conn, admin_id)
    service.create_room(conn, "Room A", 20, "", "#2563eb", admin)
    service.create_room(conn, "Room B", 20, "", "#10b981", admin)

    first = agent.execute_tool(
        conn,
        admin,
        "create_booking",
        {
            "room_name": "Room A",
            "title": "Target",
            "start": "2026-07-10 10:00",
            "end": "2026-07-10 11:00",
        },
    )
    second = agent.execute_tool(
        conn,
        admin,
        "create_booking",
        {
            "room_name": "Room B",
            "title": "Occupied",
            "start": "2026-07-10 10:00",
            "end": "2026-07-10 11:00",
        },
    )

    target_id = first["created_booking_ids"][0]
    result = agent._prepare_update_confirmation(
        conn,
        admin,
        {
            "booking_id": target_id,
            "room_name": "Room B",
        },
    )
    assert result.pending_tool is None
    assert "I found a conflict before confirmation" in result.message

    ok_result = agent._prepare_update_confirmation(
        conn,
        admin,
        {
            "booking_id": target_id,
            "title": "Target Updated",
        },
    )
    assert ok_result.pending_tool is not None
    assert ok_result.pending_tool["name"] == "update_booking"
    assert ok_result.pending_tool["arguments"]["title"] == "Target Updated"
