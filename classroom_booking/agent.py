from __future__ import annotations

import io
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from openai import OpenAI

from . import booking_service as service


DESTRUCTIVE_TOOLS = {"update_booking", "delete_booking"}
UPDATE_MUTABLE_FIELDS = ("title", "room_name", "start", "end")


def _format_tool_argument(name: str, value: Any) -> str:
    if value is None or value == "":
        return ""
    if name == "booking_id":
        return f"booking #{value}"
    if name == "room_name":
        return f"room '{value}'"
    if name == "title":
        return f"title '{value}'"
    if name == "start":
        return f"start {value}"
    if name == "end":
        return f"end {value}"
    if name == "scope":
        return f"scope {value}"
    if name == "recurrence_frequency":
        return f"recurrence {value}"
    if name == "recurrence_until":
        return f"until {value}"
    if name == "occurrence_count":
        return f"{value} occurrences"
    return f"{name.replace('_', ' ')} {value}"


def format_tool_confirmation_message(tool_name: str, args: dict[str, Any]) -> str:
    details = [
        _format_tool_argument(name, args.get(name))
        for name in [
            "booking_id",
            "title",
            "room_name",
            "start",
            "end",
            "scope",
            "recurrence_frequency",
            "recurrence_until",
            "occurrence_count",
        ]
        if args.get(name) is not None
    ]
    if not details:
        details = [
            _format_tool_argument(name, value)
            for name, value in args.items()
            if value is not None
        ]
    details_text = ", ".join([d for d in details if d])
    action = tool_name.replace("_", " ")
    if details_text:
        return f"I can {action} {details_text}. Reply `confirm` to proceed."
    return f"I can {action}. Reply `confirm` to proceed."


def format_pending_tool(tool_name: str, args: dict[str, Any]) -> str:
    action = tool_name.replace("_", " ")
    details = [
        _format_tool_argument(name, args.get(name))
        for name in [
            "booking_id",
            "title",
            "room_name",
            "start",
            "end",
            "scope",
            "recurrence_frequency",
            "recurrence_until",
            "occurrence_count",
        ]
        if args.get(name) is not None
    ]
    if not details:
        details = [
            _format_tool_argument(name, value)
            for name, value in args.items()
            if value is not None
        ]
    details_text = ", ".join([d for d in details if d])
    if details_text:
        return f"{action} {details_text}."
    return f"{action}."


def format_created_bookings_message(booking_ids: list[Any]) -> str:
    ids = [str(i) for i in booking_ids]
    if len(ids) == 1:
        return f"Your new booking ID is {ids[0]}. Please note it down for future modification or deletion."
    return f"Your new booking IDs are {', '.join(ids)}. Please note them down for future modification or deletion."


def format_action_result(result: dict[str, Any]) -> str:
    if "updated_count" in result:
        count = int(result["updated_count"])
        return f"Confirmed. Updated {count} booking{'s' if count != 1 else ''}."
    if "deleted_count" in result:
        count = int(result["deleted_count"])
        return f"Confirmed. Deleted {count} booking{'s' if count != 1 else ''}."
    if "created_booking_ids" in result:
        count = len(result["created_booking_ids"])
        ids = result["created_booking_ids"]
        if count == 1:
            return f"Confirmed. Created 1 booking, ID {ids[0]}. Please note it down for future modification or deletion."
        return f"Confirmed. Created {count} bookings, IDs {', '.join(str(i) for i in ids)}. Please note them down for future modification or deletion."
    return "Confirmed. The action completed successfully."


def _prepare_update_confirmation(conn: sqlite3.Connection, user: dict, args: dict[str, Any]) -> AgentResult:
    booking_id = args.get("booking_id")
    if booking_id is None:
        return AgentResult(message="Please provide the booking ID you want to modify.")

    booking = service.get_booking(conn, int(booking_id))
    if not booking:
        return AgentResult(message=f"I could not find booking #{booking_id}. Please verify the booking ID.")

    try:
        service.can_manage_booking(user, booking)
    except Exception as exc:
        return AgentResult(message=f"I cannot modify booking #{booking_id}: {exc}")

    has_update_fields = any(args.get(field) is not None for field in UPDATE_MUTABLE_FIELDS)
    if not has_update_fields:
        return AgentResult(
            message=(
                f"I found booking #{booking_id}: '{booking['title']}' in {booking['room_name']} from "
                f"{booking['start_ts']} to {booking['end_ts']}. Tell me what to change: title, room, start time, or end time."
            )
        )

    resolved_args = {
        "booking_id": int(booking_id),
        "title": args.get("title") if args.get("title") is not None else booking["title"],
        "room_name": args.get("room_name") if args.get("room_name") is not None else booking["room_name"],
        "start": args.get("start") if args.get("start") is not None else booking["start_ts"],
        "end": args.get("end") if args.get("end") is not None else booking["end_ts"],
        "scope": args.get("scope") or "single",
    }

    try:
        room_id = _room_id_from_name(conn, resolved_args["room_name"])
        preview = service.preview_update_booking(
            conn,
            booking_id=int(resolved_args["booking_id"]),
            actor=user,
            room_id=room_id,
            start_value=resolved_args.get("start"),
            end_value=resolved_args.get("end"),
            scope=resolved_args.get("scope") or "single",
        )
    except Exception as exc:
        return AgentResult(message=f"I checked booking #{booking_id} and found an issue: {exc}")

    if not preview.get("ok"):
        conflict = preview.get("conflict") or {}
        return AgentResult(
            message=(
                "I found a conflict before confirmation: "
                f"booking #{conflict.get('booking_id')} ({conflict.get('title')}) from "
                f"{conflict.get('start')} to {conflict.get('end')}. "
                "Please provide a different room or time."
            )
        )

    return AgentResult(
        message=format_tool_confirmation_message("update_booking", resolved_args),
        pending_tool={"name": "update_booking", "arguments": resolved_args},
    )


@dataclass
class AgentResult:
    message: str
    pending_tool: dict[str, Any] | None = None


def openai_api_key_from_streamlit(st_module: Any) -> str | None:
    try:
        if "OPENAI_API_KEY" in st_module.secrets:
            return st_module.secrets["OPENAI_API_KEY"]
    except Exception:
        pass
    return os.environ.get("OPENAI_API_KEY")


def transcribe_audio(audio_bytes: bytes, api_key: str, model: str = "gpt-4o-transcribe") -> str:
    def detect_filename(data: bytes) -> str:
        if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
            return "voice.wav"
        if data.startswith(b"fLaC"):
            return "voice.flac"
        if data.startswith(b"OggS"):
            return "voice.ogg"
        if data.startswith(b"ID3") or data.startswith(b"\xff\xfb"):
            return "voice.mp3"
        if data.startswith(b"\x1aE\xdf\xa3") or b"webm" in data[:64]:
            return "voice.webm"
        return "voice.mp3"

    client = OpenAI(api_key=api_key)
    filename = detect_filename(audio_bytes)
    with io.BytesIO(audio_bytes) as audio_file:
        setattr(audio_file, "name", filename)
        transcription = client.audio.transcriptions.create(model=model, file=audio_file)
    return getattr(transcription, "text", "") or ""


def text_to_speech(text: str, api_key: str, model: str = "gpt-4o-mini-tts", voice: str = "alloy", fmt: str = "mp3") -> bytes:
    """Synthesize speech for `text` using the OpenAI audio/speech endpoint.

    Returns raw audio bytes (e.g. MP3) or empty bytes on failure.
    """
    client = OpenAI(api_key=api_key)
    try:
        # The Python SDK surface for TTS can vary between releases. Try the
        # high-level `audio.speech.create` call and read bytes from the result.
        result = client.audio.speech.create(model=model, voice=voice, input=text, format=fmt)
        # If result is raw bytes, return directly.
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        # Try common file-like interfaces.
        if hasattr(result, "read"):
            return result.read()
        # Some SDKs return properties like `audio` or `content`.
        for attr in ("audio", "content", "data"):
            val = getattr(result, attr, None)
            if isinstance(val, (bytes, bytearray)):
                return bytes(val)
            if isinstance(val, str):
                try:
                    return val.encode("utf-8")
                except Exception:
                    pass
    except Exception:
        # Fall through to return empty bytes on any error.
        pass
    return b""


def tools_schema() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "Check available classrooms for a start and end datetime.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "end": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "room_name": {"type": "string"},
                        "min_capacity": {"type": "integer", "description": "Minimum number of participants"},
                    },
                    "required": ["start", "end"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "suggest_rooms",
                "description": "Suggest available classrooms for a time window and minimum capacity.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "end": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "min_capacity": {"type": "integer", "description": "Minimum number of participants"},
                    },
                    "required": ["start", "end"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_room_info",
                "description": "Retrieve the capacity and details for a named room.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room_name": {"type": "string"},
                    },
                    "required": ["room_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_booking",
                "description": "Create a single or recurring classroom booking.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "room_name": {"type": "string"},
                        "title": {"type": "string"},
                        "start": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "end": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "recurrence_frequency": {"type": "string", "enum": ["daily", "weekly", "monthly", "none"]},
                        "recurrence_until": {"type": "string", "description": "YYYY-MM-DD"},
                        "occurrence_count": {"type": "integer"},
                    },
                    "required": ["room_name", "title", "start", "end"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_my_bookings",
                "description": "List bookings for the current user in an optional date range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                        "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_holidays",
                "description": "List configured holidays and weekly closed days in an optional date range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                        "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "update_booking",
                "description": "Update a booking. Requires user confirmation before execution.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "booking_id": {"type": "integer"},
                        "title": {"type": "string"},
                        "room_name": {"type": "string"},
                        "start": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "end": {"type": "string", "description": "YYYY-MM-DD HH:MM"},
                        "scope": {"type": "string", "enum": ["single", "series"]},
                    },
                    "required": ["booking_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_booking",
                "description": "Cancel a booking. Requires user confirmation before execution.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "booking_id": {"type": "integer"},
                        "scope": {"type": "string", "enum": ["single", "series"]},
                    },
                    "required": ["booking_id"],
                },
            },
        },
    ]


SYSTEM_PROMPT = """You are a classroom booking assistant.
Use tools for availability, booking, listing, updating, and deleting.
You can also answer holiday and weekly closed-day questions.
Collect missing dates, times, room names, and titles before booking.
You may also answer questions about room capacity, capacity limits, and suggest rooms based on participant count.
Use 24-hour local time. The current date is always supplied by the app context and is the only authoritative "today" value.
Do not use your own internal clock or assume a different current date.
If the user provides a booking date later than the app-supplied current date, treat it as a valid future booking date.
Never tell the user a future booking date has already passed.
Only ask the user to confirm or correct the date if the provided date is before the app-supplied current date.
Destructive updates and deletes are confirmation-gated by the app."""


def chat(
    conn: sqlite3.Connection,
    user: dict,
    messages: list[dict[str, str]],
    api_key: str,
    model: str = "gpt-4.1-mini",
) -> AgentResult:
    client = OpenAI(api_key=api_key)
    contextual_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Current date: {date.today().isoformat()}. Use this current date for all booking decisions and date comparisons."},
        *messages[-12:],
    ]
    response = client.chat.completions.create(
        model=model,
        messages=contextual_messages,
        tools=tools_schema(),
        tool_choice="auto",
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    if not tool_calls:
        return AgentResult(message=message.content or "I could not produce a response.")

    tool_messages: list[dict[str, Any]] = []
    assistant_message = {
        "role": "assistant",
        "content": message.content,
        "tool_calls": [
            {
                "id": call.id,
                "type": call.type,
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }
            for call in tool_calls
        ],
    }
    contextual_messages.append(assistant_message)
    for call in tool_calls:
        args = json.loads(call.function.arguments or "{}")
        if call.function.name == "update_booking":
            return _prepare_update_confirmation(conn, user, args)
        if call.function.name in DESTRUCTIVE_TOOLS:
            return AgentResult(
                message=format_tool_confirmation_message(call.function.name, args),
                pending_tool={"name": call.function.name, "arguments": args},
            )
        result = execute_tool(conn, user, call.function.name, args)
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, default=str),
            }
        )
    contextual_messages.extend(tool_messages)
    final_response = client.chat.completions.create(model=model, messages=contextual_messages)
    message_text = final_response.choices[0].message.content or "Done."
    created_booking_ids: list[Any] = []
    for call, result in zip(tool_calls, [json.loads(message["content"]) for message in tool_messages]):
        if call.function.name == "create_booking" and isinstance(result, dict):
            created_booking_ids.extend(result.get("created_booking_ids", []))
    if created_booking_ids:
        message_text = (
            f"{message_text}\n\n{format_created_bookings_message(created_booking_ids)}"
        )
    return AgentResult(message=message_text)


def execute_tool(conn: sqlite3.Connection, user: dict, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "check_availability":
        room_id = _room_id_from_name(conn, args.get("room_name")) if args.get("room_name") else None
        return {
            "availability": service.check_availability(
                conn,
                args["start"],
                args["end"],
                room_id,
                int(args.get("min_capacity") or 0),
            )
        }
    if name == "suggest_rooms":
        return {
            "suggested_rooms": service.suggest_rooms(
                conn,
                args["start"],
                args["end"],
                int(args.get("min_capacity") or 0),
            )
        }
    if name == "get_room_info":
        return service.get_room_info(conn, args["room_name"])
    if name == "create_booking":
        room_id = _room_id_from_name(conn, args["room_name"])
        recurrence = None
        frequency = args.get("recurrence_frequency")
        if frequency and frequency != "none":
            recurrence = {
                "frequency": frequency,
                "until_date": args.get("recurrence_until"),
                "occurrence_count": args.get("occurrence_count"),
            }
        booking_ids = service.create_booking(
            conn,
            room_id=room_id,
            user_id=user["id"],
            title=args["title"],
            start_value=args["start"],
            end_value=args["end"],
            actor=user,
            recurrence=recurrence,
        )
        return {"created_booking_ids": booking_ids}
    if name == "list_my_bookings":
        start = service.parse_date(args["date_from"]) if args.get("date_from") else date.today()
        end = service.parse_date(args["date_to"]) if args.get("date_to") else start + timedelta(days=30)
        rows = service.list_bookings(conn, user_id=user["id"], start_date=start, end_date=end)
        return {"bookings": [_booking_summary(row) for row in rows]}
    if name == "list_holidays":
        date_from = service.parse_date(args["date_from"]) if args.get("date_from") else None
        date_to = service.parse_date(args["date_to"]) if args.get("date_to") else None
        holidays = [
            {
                "date": row["holiday_date"],
                "name": row["name"],
            }
            for row in service.list_holidays(conn)
            if (date_from is None or service.parse_date(row["holiday_date"]) >= date_from)
            and (date_to is None or service.parse_date(row["holiday_date"]) <= date_to)
        ]
        closed_weekdays = [service.WEEKDAY_NAMES[index] for index in sorted(service.get_closed_weekdays(conn))]
        return {
            "holidays": holidays,
            "weekly_closed_days": closed_weekdays,
        }
    if name == "update_booking":
        room_id = _room_id_from_name(conn, args["room_name"]) if args.get("room_name") else None
        count = service.update_booking(
            conn,
            booking_id=int(args["booking_id"]),
            actor=user,
            title=args.get("title"),
            room_id=room_id,
            start_value=args.get("start"),
            end_value=args.get("end"),
            scope=args.get("scope") or "single",
        )
        return {"updated_count": count}
    if name == "delete_booking":
        count = service.delete_booking(
            conn,
            booking_id=int(args["booking_id"]),
            actor=user,
            scope=args.get("scope") or "single",
        )
        return {"deleted_count": count}
    raise ValueError(f"Unknown tool: {name}")


def _room_id_from_name(conn: sqlite3.Connection, room_name: str) -> int:
    room = service.get_room_by_name(conn, room_name)
    if not room or not room["is_active"]:
        raise ValueError(f"Room not found or inactive: {room_name}")
    return int(room["id"])


def _booking_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "room": row["room_name"],
        "start": row["start_ts"],
        "end": row["end_ts"],
        "status": row["status"],
        "series_id": row["series_id"],
    }
