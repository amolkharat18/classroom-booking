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
Collect missing dates, times, room names, and titles before booking.
You may also answer questions about room capacity, capacity limits, and suggest rooms based on participant count.
Use 24-hour local time. Today is supplied by the app context.
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
        {"role": "system", "content": f"{SYSTEM_PROMPT}\nCurrent date: {date.today().isoformat()}."},
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
        if call.function.name in DESTRUCTIVE_TOOLS:
            return AgentResult(
                message=f"I can {call.function.name.replace('_', ' ')} with these details: `{json.dumps(args)}`. Reply `confirm` to proceed.",
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
    return AgentResult(message=final_response.choices[0].message.content or "Done.")


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
