from __future__ import annotations

from datetime import date, datetime, time, timedelta
import base64
import html
import inspect
import io

import pandas as pd
import plotly.express as px
import streamlit as st

from classroom_booking import APP_NAME
from classroom_booking import agent
from classroom_booking import analytics
from classroom_booking import auth
from classroom_booking import booking_service as service
from classroom_booking.db import connect, default_db_path, init_db

try:
    from streamlit_calendar import calendar
except Exception:
    calendar = None


st.set_page_config(page_title=APP_NAME, page_icon=":school:", layout="wide")


@st.cache_resource
def get_conn():
    conn = connect(default_db_path())
    init_db(conn)
    return conn

def speak_text(text: str) -> None:
    # Try server-side TTS first (higher quality, consistent audio format),
    # but respect the user's preference in `st.session_state.use_server_tts`.
    try:
        if not st.session_state.get("use_server_tts", True):
            raise RuntimeError("server-side TTS disabled by user")
        api_key = agent.openai_api_key_from_streamlit(st)
        if api_key:
            audio_bytes = agent.text_to_speech(text, api_key)
            if audio_bytes:
                st.audio(io.BytesIO(audio_bytes), format="audio/mpeg")
                return
    except Exception:
        pass

    # Fallback to browser SpeechSynthesis via an iframe if server-side TTS
    # isn't available or failed.
    safe_text = html.escape(text).replace("\n", " ")
    html_content = f"""
    <html>
      <body>
        <script>
          const msg = new SpeechSynthesisUtterance(\"{safe_text}\");
          msg.lang = 'en-US';
          window.speechSynthesis.cancel();
          window.speechSynthesis.speak(msg);
        </script>
      </body>
    </html>
    """
    data_url = "data:text/html;charset=utf-8," + html_content.replace("\n", "%0A").replace('"', '%22')
    # Use top-level `st.iframe` when available (newer Streamlit); fall back to
    # `streamlit.components.v1.iframe` for older Streamlit versions.
    if hasattr(st, "iframe"):
        st.iframe(
            data_url,
            height=1,
            width="content",
        )
    else:
        import streamlit.components.v1 as components

        components.iframe(
            data_url,
            height=1,
            width="content",
        )


def render_global_styles() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html:not([data-theme="dark"]),
        html:not([data-theme="dark"]) body,
        html:not([data-theme="dark"]) [class*="css"] {
            font-family: 'Inter', sans-serif !important;
            color: #0f172a;
        }

        html[data-theme="dark"],
        html[data-theme="dark"] body,
        html[data-theme="dark"] [class*="css"],
        body[data-theme="dark"],
        body[data-theme="dark"] [class*="css"] {
            font-family: 'Inter', sans-serif !important;
            color: #e2e8f0 !important;
        }

        div[data-testid="stAppViewContainer"] {
            background: #f8fafc;
        }

        html[data-theme="dark"] div[data-testid="stAppViewContainer"],
        body[data-theme="dark"] div[data-testid="stAppViewContainer"] {
            background: #020617;
        }

        div[data-testid="stSidebar"] {
            background: #ffffff;
            box-shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
            border-right: 1px solid rgba(15, 23, 42, 0.08);
            padding-top: 1.2rem;
        }

        html[data-theme="dark"] div[data-testid="stSidebar"],
        body[data-theme="dark"] div[data-testid="stSidebar"] {
            background: #020617;
            border-right: 1px solid rgba(148, 163, 184, 0.24);
            color: #e2e8f0;
        }

        html[data-theme="dark"] .stSidebar > div,
        body[data-theme="dark"] .stSidebar > div,
        html[class*="theme-dark"] .stSidebar > div,
        body[class*="theme-dark"] .stSidebar > div,
        html.dark .stSidebar > div,
        body.dark .stSidebar > div,
        :where(html, body)[data-theme="dark"] .stSidebar > div {
            background: transparent !important;
        }

        section.main .block-container {
            max-width: 1380px;
            padding-top: 1.4rem;
            padding-bottom: 2rem;
            padding-left: 2rem;
            padding-right: 2rem;
        }

        html[data-theme="dark"] .block-container,
        body[data-theme="dark"] .block-container,
        html[class*="theme-dark"] .block-container,
        body[class*="theme-dark"] .block-container,
        html.dark .block-container,
        body.dark .block-container,
        :where(html, body)[data-theme="dark"] .block-container {
            background: #020617 !important;
        }

        html[data-theme="dark"] .stForm,
        body[data-theme="dark"] .stForm,
        :where(html, body)[data-theme="dark"] .stForm,
        html[data-theme="dark"] .stExpander,
        body[data-theme="dark"] .stExpander,
        :where(html, body)[data-theme="dark"] .stExpander {
            background: #0f172a !important;
            color: #e2e8f0 !important;
        }

        div[data-testid="stSidebar"] {
            background: #ffffff;
            box-shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
            border-right: 1px solid rgba(15, 23, 42, 0.08);
            padding-top: 1.2rem;
        }

        button[data-baseweb="button"] {
            border-radius: 999px !important;
            padding: 0.85rem 1.25rem !important;
            font-weight: 600 !important;
            min-height: 3rem;
            transition: all 0.2s ease;
            color: #ffffff !important;
            background: #2563eb !important;
        }

        button[data-baseweb="button"]:not(:disabled):hover {
            filter: brightness(0.94);
        }

        html[data-theme="dark"] button[data-baseweb="button"] {
            color: #ffffff !important;
            background: #2563eb !important;
        }

        .stTextInput>div>div>input,
        .stNumberInput>div>div>input,
        .stSelectbox>div>div>div,
        .stDateInput>div>div>input,
        .stTimeInput>div>div>input,
        .stTextArea>div>textarea {
            border-radius: 0.85rem !important;
        }

        .section-card {
            background: #ffffff;
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 1.25rem;
            padding: 1.25rem 1.4rem;
            margin-bottom: 1.4rem;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.04);
        }

        .sample-prompt-card {
            background: #f8fafc;
            border-radius: 1rem;
            padding: 0.95rem 1rem;
            border: 1px solid rgba(15, 23, 42, 0.08);
            overflow-wrap: anywhere;
        }

        html[data-theme="dark"] .sample-prompt-card,
        body[data-theme="dark"] .sample-prompt-card,
        html[class*="theme-dark"] .sample-prompt-card,
        body[class*="theme-dark"] .sample-prompt-card,
        html.dark .sample-prompt-card,
        body.dark .sample-prompt-card,
        :where(html, body)[data-theme="dark"] .sample-prompt-card {
            background: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(148, 163, 184, 0.18) !important;
        }

        html[data-theme="dark"] .sample-prompt-card code,
        body[data-theme="dark"] .sample-prompt-card code,
        :where(html, body)[data-theme="dark"] .sample-prompt-card code {
            color: #e2e8f0 !important;
            background: transparent !important;
            font-size: 0.95rem;
        }

        html[data-theme="dark"] .sample-prompt-card {
            color: #e2e8f0 !important;
        }

        html[data-theme="dark"] .section-card,
        body[data-theme="dark"] .section-card,
        html[class*="theme-dark"] .section-card,
        body[class*="theme-dark"] .section-card,
        html.dark .section-card,
        body.dark .section-card,
        :where(html, body)[data-theme="dark"] .section-card {
            background: #080b14 !important;
            border: 1px solid rgba(148, 163, 184, 0.16) !important;
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.32) !important;
        }

        html[data-theme="dark"] .section-card *,
        body[data-theme="dark"] .section-card *,
        :where(html, body)[data-theme="dark"] .section-card * {
            color: #e2e8f0 !important;
        }

        .section-card-title {
            font-size: 1.35rem;
            font-weight: 700;
            margin-bottom: 0.3rem;
            color: #0f172a;
        }

        html[data-theme="dark"] .section-card-title,
        body[data-theme="dark"] .section-card-title,
        :where(html, body)[data-theme="dark"] .section-card-title {
            color: #ffffff !important;
        }

        .section-card-subtitle {
            color: #475569;
            margin-top: 0.15rem;
            line-height: 1.6;
        }

        html[data-theme="dark"] .section-card-subtitle,
        body[data-theme="dark"] .section-card-subtitle,
        :where(html, body)[data-theme="dark"] .section-card-subtitle {
            color: #cbd5e1 !important;
        }

        :where(html, body)[data-theme="dark"] .block-container,
        :where(html, body)[data-theme="dark"] .block-container *,
        :where(html, body)[data-theme="dark"] .stMarkdown,
        :where(html, body)[data-theme="dark"] .stMarkdown *,
        :where(html, body)[data-theme="dark"] .stText,
        :where(html, body)[data-theme="dark"] .stText *,
        :where(html, body)[data-theme="dark"] h1,
        :where(html, body)[data-theme="dark"] h2,
        :where(html, body)[data-theme="dark"] h3,
        :where(html, body)[data-theme="dark"] h4,
        :where(html, body)[data-theme="dark"] h5,
        :where(html, body)[data-theme="dark"] h6,
        :where(html, body)[data-theme="dark"] p,
        :where(html, body)[data-theme="dark"] span,
        :where(html, body)[data-theme="dark"] strong,
        :where(html, body)[data-theme="dark"] label,
        :where(html, body)[data-theme="dark"] button,
        :where(html, body)[data-theme="dark"] input,
        :where(html, body)[data-theme="dark"] textarea,
        :where(html, body)[data-theme="dark"] select {
            color: #e2e8f0 !important;
        }

        :where(html, body)[data-theme="dark"] .stTextInput>div>div>input,
        :where(html, body)[data-theme="dark"] .stNumberInput>div>div>input,
        :where(html, body)[data-theme="dark"] .stDateInput>div>div>input,
        :where(html, body)[data-theme="dark"] .stTimeInput>div>div>input,
        :where(html, body)[data-theme="dark"] .stSelectbox>div>div>div {
            background: #111827 !important;
            color: #e2e8f0 !important;
            border-color: rgba(148, 163, 184, 0.3) !important;
        }

        html[data-theme="dark"] *,
        body[data-theme="dark"] *,
        :where(html, body)[data-theme="dark"] * {
            color: #e2e8f0 !important;
        }

        .voice-listening {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.85rem 1rem;
            border-radius: 1rem;
            background: #e0f2fe;
            color: #0f172a;
            font-weight: 600;
            margin-bottom: 1rem;
        }

        html[data-theme="dark"] .voice-listening {
            background: rgba(59, 130, 246, 0.16) !important;
            color: #e2e8f0;
        }

        .voice-listening .voice-pulse {
            width: 0.9rem;
            height: 0.9rem;
            border-radius: 50%;
            background: #2563eb;
            animation: voice-pulse 1.4s infinite ease-in-out;
        }

        .voice-transcript-panel {
            border-radius: 1rem;
            padding: 1rem;
            background: #eef2ff;
            margin-bottom: 1rem;
            border: 1px solid rgba(59, 130, 246, 0.16);
        }

        html[data-theme="dark"] .voice-transcript-panel {
            background: rgba(59, 130, 246, 0.12) !important;
            border: 1px solid rgba(59, 130, 246, 0.32) !important;
        }

        .voice-waveform {
            display: flex;
            gap: 0.4rem;
            align-items: flex-end;
            margin-bottom: 1rem;
        }

        .voice-waveform span {
            display: inline-block;
            width: 0.5rem;
            height: 0.9rem;
            border-radius: 0.35rem;
            background: linear-gradient(180deg, #2563eb, #3b82f6);
            animation: voice-wave 1.2s infinite ease-in-out;
        }

        .voice-waveform span:nth-child(2) {
            animation-delay: 0.1s;
            height: 1.4rem;
        }

        .voice-waveform span:nth-child(3) {
            animation-delay: 0.2s;
            height: 0.85rem;
        }

        .voice-waveform span:nth-child(4) {
            animation-delay: 0.3s;
            height: 1.2rem;
        }

        .voice-waveform span:nth-child(5) {
            animation-delay: 0.4s;
            height: 1rem;
        }

        .voice-transcript-card {
            background: #f8fafc;
            border: 1px solid rgba(15, 23, 42, 0.06);
            border-radius: 1rem;
            padding: 1rem 1.1rem;
            margin-top: 0.8rem;
            margin-bottom: 1rem;
            font-size: 0.96rem;
            color: #0f172a;
        }

        html[data-theme="dark"] .voice-transcript-card {
            background: rgba(15, 23, 42, 0.76) !important;
            border: 1px solid rgba(148, 163, 184, 0.2) !important;
            color: #e2e8f0;
        }

        @keyframes voice-pulse {
            0%, 100% { transform: scale(1); opacity: 0.65; }
            50% { transform: scale(1.35); opacity: 1; }
        }

        @keyframes voice-wave {
            0%, 100% { transform: scaleY(0.65); }
            50% { transform: scaleY(1.5); }
        }

        .stTabs [role="tablist"] button {
            border-radius: 999px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def section_card(title: str, subtitle: str = "") -> None:
    subtitle_html = f"<div class='section-card-subtitle'>{subtitle}</div>" if subtitle else ""
    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-card-title">{title}</div>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

def main() -> None:
    conn = get_conn()
    st.title(APP_NAME)
    st.caption("SQLite classroom booking with chat, calendar management, holidays, recurrence, and analytics.")

    if auth.user_count(conn) == 0:
        first_admin_form(conn)
        return

    user = st.session_state.get("user")
    if not user:
        login_form(conn)
        return

    with st.sidebar:
        st.markdown(f"Signed in as **{user['username']}**")
        st.caption("Admin" if user["is_admin"] else "User")
        st.divider()
        st.markdown("**Signed in as**")
        st.markdown(f"<strong>{user['username']}</strong>", unsafe_allow_html=True)
        st.write("")
        if st.button("Sign out", width="stretch"):
            st.session_state.clear()
            st.rerun()

    tabs = ["Chat", "Voice Agent", "Calendar", "My Bookings", "Availability Heatmap"]
    if user["is_admin"]:
        tabs.append("Admin")
    selected_tabs = st.tabs(tabs)
    render_chat(conn, user, selected_tabs[0])
    render_voice_agent(conn, user, selected_tabs[1])
    render_calendar(conn, user, selected_tabs[2])
    render_my_bookings(conn, user, selected_tabs[3])
    render_heatmap(conn, selected_tabs[4])
    if user["is_admin"]:
        render_admin(conn, user, selected_tabs[5])


def first_admin_form(conn) -> None:
    st.info("Create the first administrator account.")
    with st.form("first_admin"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Create admin")
    if submitted:
        try:
            user_id = auth.create_user(conn, username, password, is_admin=True)
            st.session_state.user = auth.get_user(conn, user_id)
            st.success("Admin created.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def login_form(conn) -> None:
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        user = auth.authenticate(conn, username, password)
        if user:
            st.session_state.user = user
            st.rerun()
        st.error("Invalid username or password.")


def render_chat(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("Booking Assistant")
        api_key = agent.openai_api_key_from_streamlit(st)
        if not api_key:
            st.warning("OPENAI_API_KEY is not configured. The UI still works, but chat is disabled.")
            return
        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = [
                {"role": "assistant", "content": "Ask me to check availability, book a room, or manage your bookings."}
            ]
        render_sample_prompts()
        for message in st.session_state.chat_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if "chat_input" not in st.session_state:
            st.session_state["chat_input"] = ""
        prompt = st.chat_input("Example: Book Room-101 tomorrow 10 AM to 11 AM for Physics", key="chat_input")
        if prompt:
            st.session_state.chat_messages.append({"role": "user", "content": prompt})
            if st.session_state.get("pending_tool") and prompt.strip().lower() in {"confirm", "yes", "proceed"}:
                pending = st.session_state.pop("pending_tool")
                try:
                    result = agent.execute_tool(conn, user, pending["name"], pending["arguments"])
                    reply = f"Confirmed. Result: `{result}`"
                except Exception as exc:
                    reply = f"I could not complete that action: {exc}"
            else:
                try:
                    result = agent.chat(conn, user, st.session_state.chat_messages, api_key)
                    reply = result.message
                    if result.pending_tool:
                        st.session_state.pending_tool = result.pending_tool
                except Exception as exc:
                    reply = f"Chat failed: {exc}"
            st.session_state.chat_messages.append({"role": "assistant", "content": reply})
            st.rerun()


def render_voice_agent(conn, user: dict, tab) -> None:
    with tab:
        section_card(
            "Voice Agent",
            "Use your microphone to speak booking requests and questions. The voice assistant will transcribe and execute the same actions as chat.",
        )
        api_key = agent.openai_api_key_from_streamlit(st)
        if not api_key:
            st.warning("OPENAI_API_KEY is not configured. Voice input is disabled.")
            return

        if "voice_messages" not in st.session_state:
            st.session_state.voice_messages = [
                {"role": "assistant", "content": "Ask me to check availability, book a room, or manage your bookings."}
            ]
        if "voice_pending_tool" not in st.session_state:
            st.session_state.voice_pending_tool = None
        if "voice_active" not in st.session_state:
            st.session_state.voice_active = False
        if "voice_speaking" not in st.session_state:
            st.session_state.voice_speaking = False
        if "voice_last_audio_bytes" not in st.session_state:
            st.session_state.voice_last_audio_bytes = None
        if "voice_last_transcript" not in st.session_state:
            st.session_state.voice_last_transcript = ""
        st.markdown("### Voice conversation")
        use_server_tts_default = st.session_state.get("use_server_tts", True)
        use_server_tts_label = (
            "Server-side TTS (higher quality, uses OpenAI)"
            if use_server_tts_default
            else "Browser TTS (fallback, local speech synthesis)"
        )
        st.checkbox(
            use_server_tts_label,
            value=use_server_tts_default,
            key="use_server_tts",
            help="Server-side TTS uses OpenAI audio generation and requires OPENAI_API_KEY.",
        )

        if not st.session_state.voice_active:
            if st.button("Start voice conversation", key="voice_start"):
                greeting_text = "Hello! I am your voice booking assistant. How can I help you today?"
                st.session_state.voice_active = True
                st.session_state.voice_speaking = False
                st.session_state.voice_last_transcript = ""
                st.session_state.voice_last_audio_bytes = None
                st.session_state.voice_messages.append(
                    {
                        "role": "assistant",
                        "content": greeting_text,
                    }
                )
                try:
                    speak_text(greeting_text)
                except Exception:
                    pass

            st.info("Press Start to begin a live voice conversation in English.")
            st.write("Once started, speak your request and the assistant will respond.")
            for message in st.session_state.voice_messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
            return

        stop_col, _ = st.columns([0.2, 0.8])
        if stop_col.button("Stop conversation", key="voice_stop"):
            st.session_state.voice_active = False
            st.session_state.voice_speaking = False
            st.success("Voice conversation ended. Start again to continue.")
            st.rerun()

        if st.session_state.voice_speaking:
            st.markdown(
                "<div class='voice-listening voice-speaking'><span class='voice-pulse'></span> Assistant speaking... the waveform shows playback.</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='voice-listening'><span class='voice-pulse'></span> Listening... speak your request in English.</div>",
                unsafe_allow_html=True,
            )
        st.markdown(
            "<div class='voice-waveform'><span></span><span></span><span></span><span></span><span></span></div>",
            unsafe_allow_html=True,
        )
        audio_bytes = None
        st.info(
            "Click the microphone, speak your request, and stop recording when finished. "
            "A waveform appears while recording and the transcript panel shows status live."
        )
        try:
            from audiorecorder import audiorecorder as st_audiorecorder
        except Exception:
            try:
                from streamlit_audiorecorder import st_audiorecorder
            except Exception:
                st.warning(
                    "Install `audiorecorder` or `streamlit-audiorecorder` to record directly in the browser, or upload an audio file below."
                )
                st_audiorecorder = None

        if st_audiorecorder is not None:
            try:
                recorder_args = {}
                sig = inspect.signature(st_audiorecorder)
                if "show_visualizer" in sig.parameters:
                    recorder_args = {
                        "show_visualizer": True,
                        "pause_prompt": "Pause recording",
                        "stop_prompt": "Stop recording",
                    }
                    audio_recording = st_audiorecorder("Record your voice", key="voice_recorder", **recorder_args)
                else:
                    audio_recording = st_audiorecorder("Record your voice", key="voice_recorder", format="mp3")
            except TypeError:
                audio_recording = st_audiorecorder("Record your voice", key="voice_recorder")
            except Exception:
                audio_recording = None

            if audio_recording is not None:
                if hasattr(audio_recording, "export"):
                    with io.BytesIO() as buffer:
                        audio_recording.export(buffer, format="mp3")
                        audio_bytes = buffer.getvalue()
                elif isinstance(audio_recording, bytes):
                    audio_bytes = audio_recording
                elif isinstance(audio_recording, str):
                    raw_audio = audio_recording
                    if raw_audio.startswith("data:"):
                        raw_audio = raw_audio.split(",", 1)[1]
                    try:
                        audio_bytes = base64.b64decode(raw_audio)
                    except Exception:
                        audio_bytes = raw_audio.encode("utf-8")

        if audio_bytes is None:
            uploaded_audio = st.file_uploader("Upload recorded voice file", type=["mp3", "wav", "m4a"])
            if uploaded_audio is not None:
                audio_bytes = uploaded_audio.read()

        live_transcript_text = st.session_state.voice_last_transcript
        if not live_transcript_text:
            live_transcript_text = (
                "Recording now... the waveform is live while you speak. "
                "The transcript will update after you stop speaking."
            )
        st.markdown(
            "<div class='voice-transcript-panel'><strong>Live transcript</strong><div class='voice-transcript-card'>"
            + html.escape(live_transcript_text)
            + "</div></div>",
            unsafe_allow_html=True,
        )

        if audio_bytes is not None and audio_bytes != st.session_state.voice_last_audio_bytes:
            st.session_state.voice_last_audio_bytes = audio_bytes
            st.audio(audio_bytes)
            st.session_state.voice_last_transcript = "Processing audio... transcribing now."
            with st.spinner("Transcribing and processing your request..."):
                try:
                    transcript = agent.transcribe_audio(audio_bytes, api_key)
                except Exception as exc:
                    st.error(f"Voice transcription failed: {exc}")
                    transcript = ""

                if transcript:
                    st.session_state.voice_last_transcript = transcript
                    st.markdown("#### You spoke")
                    st.markdown(
                        f"<div class='voice-transcript-card'>{html.escape(transcript)}</div>",
                        unsafe_allow_html=True,
                    )
                    if (
                        st.session_state.get("voice_pending_tool")
                        and transcript.strip().lower() in {"confirm", "yes", "proceed"}
                    ):
                        pending = st.session_state.pop("voice_pending_tool")
                        try:
                            result = agent.execute_tool(conn, user, pending["name"], pending["arguments"])
                            reply = f"Confirmed. Result: `{result}`"
                        except Exception as exc:
                            reply = f"I could not complete that action: {exc}"
                    else:
                        st.session_state.voice_messages.append({"role": "user", "content": transcript})
                        try:
                            result = agent.chat(conn, user, st.session_state.voice_messages, api_key)
                            reply = result.message
                            if result.pending_tool:
                                st.session_state.voice_pending_tool = result.pending_tool
                        except Exception as exc:
                            reply = f"Voice assistant failed: {exc}"
                    st.session_state.voice_messages.append({"role": "assistant", "content": reply})
                    st.session_state.voice_speaking = True
                    try:
                        speak_text(reply)
                    except Exception:
                        pass
                    st.rerun()

        for message in st.session_state.voice_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if st.session_state.voice_pending_tool:
            pending = st.session_state.voice_pending_tool
            st.warning(
                f"Confirm the following action before it runs: {pending['name']} with {pending['arguments']}"
            )
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Confirm voice action", key="voice_confirm"):
                try:
                    result = agent.execute_tool(conn, user, pending["name"], pending["arguments"])
                    confirmation = f"Confirmed. Result: `{result}`"
                    st.session_state.voice_messages.append(
                        {"role": "assistant", "content": confirmation}
                    )
                    try:
                        speak_text(confirmation)
                    except Exception:
                        pass
                    st.session_state.voice_pending_tool = None
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
            if cancel_col.button("Cancel voice action", key="voice_cancel"):
                st.session_state.voice_pending_tool = None
                st.success("Voice action cancelled.")


def render_sample_prompts() -> None:
    examples = {
        "Check availability": [
            "Which classrooms are available on 15-Jul-2026 from 10 AM to 12 PM?",
            "Is Room-101 free on 16-Jul-2026 from 2 PM to 3:30 PM?",
        ],
        "Single booking": [
            "Book Room-101 on 15-Jul-2026 from 10 AM to 11 AM for Physics lecture.",
            "Reserve any available classroom on 17-Jul-2026 from 9 AM to 10:30 AM for project discussion.",
            "Find a classroom for 12 people on 20-Jul-2026 from 2 PM to 3 PM.",
        ],
        "Capacity questions": [
            "What is the capacity of Room-101?",
            "Which rooms can fit 25 participants on 22-Jul-2026 from 9 AM to 10:30 AM?",
        ],
        "Modify or delete booking": [
            "Change booking 12 to Room-101 on 21-Jul-2026 from 1 PM to 2 PM.",
            "Cancel booking 15.",
        ],
        "Recurring booking": [
            "Book Room-101 every Monday from 20-Jul-2026 to 14-Sep-2026, 11 AM to 12 PM, for Chemistry lab.",
            "Create a weekly booking for Room-102 starting 22-Jul-2026 from 3 PM to 4 PM for 8 occurrences named Tutorial session.",
        ],
        "Modify booking": [
            "Change booking 12 to Room-101 on 21-Jul-2026 from 1 PM to 2 PM.",
            "Update the title of booking 15 to Guest lecture.",
        ],
        "Delete booking": [
            "Delete booking 12.",
            "Cancel the whole recurring series for booking 18.",
        ],
    }
    with st.expander("Sample prompts", expanded=False):
        st.subheader("Booking IDs")
        st.info("Find booking IDs in the My Bookings tab — use these IDs to modify or cancel bookings.")
        for heading, prompts in examples.items():
            st.markdown(f"**{heading}**")
            for i, p in enumerate(prompts):
                cols = st.columns([0.84, 0.16], gap="small")
                cols[0].markdown(
                    f"<div class='sample-prompt-card'><code>{html.escape(p)}</code></div>",
                    unsafe_allow_html=True,
                )
                with cols[1]:
                    if st.button("Copy", key=f"copy_{heading}_{i}"):
                        st.session_state["chat_input"] = p
                        try:
                            st.rerun()
                        except Exception:
                            st.success("Prompt copied to chat input. Click the chat box to edit and submit.")
                st.markdown("<div style='height:0.55rem'></div>", unsafe_allow_html=True)


def render_calendar(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("Booking Calendar")
        col1, col2, col3 = st.columns(3)
        today = date.today()
        with col1:
            start = st.date_input("From", today - timedelta(days=14), key="cal_from")
        with col2:
            end = st.date_input("To", today + timedelta(days=45), key="cal_to")
        with col3:
            view_options = {
                "Month": "dayGridMonth",
                "Week": "timeGridWeek",
                "Day": "timeGridDay",
                "List (week)": "listWeek",
                "Multi-month": "multiMonthYear",
            }
            selected_view_label = st.selectbox("View", list(view_options.keys()), index=0)
            view = view_options[selected_view_label]
        closed_weekdays = service.get_closed_weekdays(conn)
        rows = service.list_bookings(conn, start_date=start, end_date=end)
        events = [
            {
                "id": str(row["id"]),
                "title": f"{row['room_name']}: {row['title']}",
                "start": row["start_ts"],
                "end": row["end_ts"],
                "backgroundColor": row["room_color"],
                "borderColor": row["room_color"],
            }
            for row in rows
        ]
        events.extend(calendar_holiday_events(conn, start, end))
        if calendar:
            options = {
                "initialView": view,
                "height": 720,
                "selectable": True,
                "editable": False,
                "nowIndicator": True,
                "hiddenDays": fullcalendar_hidden_days(closed_weekdays),
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,timeGridWeek,timeGridDay,listWeek,multiMonthYear",
                },
            }
            calendar(events=events, options=options, key=f"calendar_{view}_{start}_{end}")
        else:
            st.warning("Install streamlit-calendar for interactive calendar views.")
            st.dataframe(pd.DataFrame(events), width="stretch")
        st.caption("Date-specific holidays are shown in red. Weekly closed days are hidden and cannot be booked.")

        st.divider()
        quick_booking_form(conn, user)


def fullcalendar_hidden_days(closed_weekdays: set[int]) -> list[int]:
    return sorted((weekday + 1) % 7 for weekday in closed_weekdays)


def calendar_holiday_events(conn, start: date, end: date) -> list[dict]:
    events = []
    closed_weekdays = service.get_closed_weekdays(conn)
    for holiday in service.list_holidays(conn):
        holiday_date = date.fromisoformat(holiday["holiday_date"])
        if holiday_date.weekday() in closed_weekdays:
            continue
        if start <= holiday_date <= end:
            events.append(
                {
                    "id": f"holiday-{holiday['id']}",
                    "title": f"Holiday: {holiday['name']}",
                    "start": holiday_date.isoformat(),
                    "end": (holiday_date + timedelta(days=1)).isoformat(),
                    "allDay": True,
                    "backgroundColor": "#dc2626",
                    "borderColor": "#991b1b",
                    "textColor": "#ffffff",
                    "editable": False,
                }
            )
    return events


def quick_booking_form(conn, user: dict) -> None:
    st.markdown("#### Quick Booking")
    rooms = service.list_rooms(conn)
    if not rooms:
        st.info("No active rooms exist yet. Ask an admin to create rooms.")
        return
    room_options = {room["name"]: int(room["id"]) for room in rooms}
    with st.form("quick_booking"):
        title = st.text_input("Title")
        room_name = st.selectbox("Room", list(room_options))
        col1, col2 = st.columns(2)
        with col1:
            booking_date = st.date_input("Date", date.today())
            start_time = st.time_input("Start time", time(9, 0))
        with col2:
            end_date = st.date_input("End date", booking_date)
            end_time = st.time_input("End time", time(10, 0))
        date_range_start = datetime.combine(booking_date, time.min)
        date_range_end = datetime.combine(end_date + timedelta(days=1), time.min)
        holiday_dates = service.holiday_dates_between(conn, date_range_start, date_range_end)
        closed_dates = service.closed_dates_between(conn, date_range_start, date_range_end)
        if holiday_dates:
            st.warning(f"Bookings are not allowed on holidays: {', '.join(sorted(holiday_dates))}.")
        if closed_dates:
            st.warning(f"Bookings are not allowed on closed days: {service.format_closed_dates(closed_dates)}.")
        recurring = st.checkbox("Recurring")
        recurrence = None
        if recurring:
            c1, c2, c3 = st.columns(3)
            frequency = c1.selectbox("Frequency", ["daily", "weekly", "monthly"])
            until = c2.date_input("Until", booking_date + timedelta(days=30))
            count = c3.number_input("Max occurrences", min_value=1, max_value=500, value=10)
            recurrence = {"frequency": frequency, "until_date": until, "occurrence_count": int(count)}
        submitted = st.form_submit_button("Create booking", disabled=bool(holiday_dates or closed_dates))
    if submitted:
        try:
            ids = service.create_booking(
                conn,
                room_options[room_name],
                user["id"],
                title,
                datetime.combine(booking_date, start_time),
                datetime.combine(end_date, end_time),
                user,
                recurrence,
            )
            st.success(f"Created {len(ids)} booking(s).")
        except Exception as exc:
            st.error(str(exc))


def render_my_bookings(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("My Bookings" if not user["is_admin"] else "Bookings")
        rows = service.list_bookings(conn, user_id=None if user["is_admin"] else user["id"])
        if not rows:
            st.info("No active bookings.")
            return
        rooms = service.list_rooms(conn)
        room_options = {room["name"]: int(room["id"]) for room in rooms}
        for row in rows:
            label = f"#{row['id']} {row['title']} - {row['room_name']} - {row['start_ts']} to {row['end_ts']}"
            with st.expander(label):
                st.write(f"Booked by: {row['username']}")
                with st.form(f"edit_{row['id']}"):
                    title = st.text_input("Title", row["title"])
                    room_names = list(room_options)
                    current_index = room_names.index(row["room_name"]) if row["room_name"] in room_names else 0
                    room_name = st.selectbox("Room", room_names, index=current_index)
                    start_dt = service.db_to_dt(row["start_ts"])
                    end_dt = service.db_to_dt(row["end_ts"])
                    col1, col2 = st.columns(2)
                    with col1:
                        start_date = st.date_input("Start date", start_dt.date(), key=f"sd_{row['id']}")
                        start_time = st.time_input("Start time", start_dt.time(), key=f"st_{row['id']}")
                    with col2:
                        end_date = st.date_input("End date", end_dt.date(), key=f"ed_{row['id']}")
                        end_time = st.time_input("End time", end_dt.time(), key=f"et_{row['id']}")
                    scope = st.radio("Scope", ["single", "series"], horizontal=True, key=f"scope_{row['id']}")
                    c1, c2 = st.columns(2)
                    save = c1.form_submit_button("Save changes")
                    cancel = c2.form_submit_button("Delete booking")
                if save:
                    try:
                        count = service.update_booking(
                            conn,
                            int(row["id"]),
                            user,
                            title=title,
                            room_id=room_options[room_name],
                            start_value=datetime.combine(start_date, start_time),
                            end_value=datetime.combine(end_date, end_time),
                            scope=scope,
                        )
                        st.success(f"Updated {count} booking(s).")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                delete_key = f"confirm_delete_booking_{row['id']}"
                if cancel:
                    st.session_state[delete_key] = scope
                    st.rerun()
                pending_delete_scope = st.session_state.get(delete_key)
                if pending_delete_scope:
                    st.warning(
                        f"Confirm delete booking #{row['id']} ({pending_delete_scope}). This cannot be undone."
                    )
                    confirm_col, cancel_col = st.columns(2)
                    if confirm_col.button("Confirm delete", key=f"do_delete_booking_{row['id']}"):
                        try:
                            count = service.delete_booking(conn, int(row["id"]), user, scope=pending_delete_scope)
                            st.session_state.pop(delete_key, None)
                            st.success(f"Deleted {count} booking(s).")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
                    if cancel_col.button("Cancel delete", key=f"cancel_delete_booking_{row['id']}"):
                        st.session_state.pop(delete_key, None)
                        st.rerun()


def render_heatmap(conn, tab) -> None:
    with tab:
        st.subheader("Room Availability Heatmap")
        c1, c2 = st.columns(2)
        start = c1.date_input("Analytics from", date.today().replace(day=1), key="heat_from")
        end = c2.date_input("Analytics to", date.today() + timedelta(days=30), key="heat_to")
        heatmap = analytics.heatmap_dataframe(conn, start, end)
        if heatmap.empty:
            st.info("No bookings in the selected range.")
        else:
            fig = px.imshow(
                heatmap,
                text_auto=True,
                aspect="auto",
                color_continuous_scale="Blues",
                labels={"color": "Booked hours"},
            )
            st.plotly_chart(fig, width="stretch")
        util = analytics.utilization_dataframe(conn, start, end)
        if not util.empty:
            st.markdown("#### Utilization")
            st.dataframe(util, width="stretch", hide_index=True)


def render_admin(conn, user: dict, tab) -> None:
    with tab:
        st.subheader("Admin")
        room_tab, user_tab, report_tab, holiday_tab, audit_tab = st.tabs(["Rooms", "Users", "Reports", "Holidays", "Audit"])
        with room_tab:
            admin_rooms(conn, user)
        with user_tab:
            admin_users(conn, user)
        with report_tab:
            admin_reports(conn)
        with holiday_tab:
            admin_holidays(conn, user)
        with audit_tab:
            rows = conn.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 200").fetchall()
            st.dataframe(pd.DataFrame([dict(row) for row in rows]), width="stretch", hide_index=True)


def admin_rooms(conn, user: dict) -> None:
    with st.form("add_room"):
        st.markdown("#### Add Room")
        name = st.text_input("Room name")
        capacity = st.number_input("Capacity", min_value=0, value=30)
        location = st.text_input("Location")
        color = st.color_picker("Room color", "#2563eb")
        submitted = st.form_submit_button("Add room")
    if submitted:
        try:
            service.create_room(conn, name, capacity, location, color, user)
            st.success("Room added.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    st.markdown("#### Room Color Legend")
    for room in service.list_rooms(conn, active_only=False):
        with st.expander(f"{room['name']} ({'active' if room['is_active'] else 'inactive'})"):
            with st.form(f"room_{room['id']}"):
                name = st.text_input("Name", room["name"])
                capacity = st.number_input("Capacity", min_value=0, value=int(room["capacity"]))
                location = st.text_input("Location", room["location"])
                color = st.color_picker("Color", room["color"])
                active = st.checkbox("Active", bool(room["is_active"]))
                save = st.form_submit_button("Save room")
            if save:
                try:
                    service.update_room(conn, int(room["id"]), name, capacity, location, color, active, user)
                    st.success("Room updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def admin_users(conn, user: dict) -> None:
    with st.form("add_user"):
        st.markdown("#### Add User")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        is_admin = st.checkbox("Admin")
        submitted = st.form_submit_button("Add user")
    if submitted:
        try:
            auth.create_user(conn, username, password, is_admin, actor_id=user["id"])
            st.success("User added.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    for row in auth.list_users(conn):
        with st.expander(f"{row['username']} ({'admin' if row['is_admin'] else 'user'})"):
            c1, c2 = st.columns(2)
            is_admin = c1.checkbox("Admin", bool(row["is_admin"]), key=f"admin_{row['id']}")
            is_active = c2.checkbox("Active", bool(row["is_active"]), key=f"active_{row['id']}")
            new_password = st.text_input("New password", type="password", key=f"pw_{row['id']}")
            if st.button("Save user", key=f"save_user_{row['id']}"):
                try:
                    auth.set_user_admin(conn, int(row["id"]), is_admin, user["id"])
                    auth.set_user_active(conn, int(row["id"]), is_active, user["id"])
                    if new_password:
                        auth.reset_password(conn, int(row["id"]), new_password, user["id"])
                    st.success("User updated.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def admin_reports(conn) -> None:
    st.markdown("#### Booking Reports")
    c1, c2 = st.columns(2)
    today = date.today()
    start = c1.date_input("Analytics from", today.replace(day=1), key="report_from")
    end = c2.date_input("Analytics to", today + timedelta(days=30), key="report_to")
    if start > end:
        st.error("Start date must be before end date.")
        return

    if not hasattr(analytics, "user_bookings_summary") or not hasattr(analytics, "room_booking_summary"):
        st.error(
            "Admin report functionality is not available in the deployed app version yet. "
            "Please redeploy with the latest code changes."
        )
        return

    user_summary = analytics.user_bookings_summary(conn, start, end)
    room_summary = analytics.room_booking_summary(conn, start, end)
    weekday_summary = analytics.weekday_booking_summary(conn, start, end)

    total_bookings = user_summary["total_bookings"].sum() if not user_summary.empty else 0
    total_hours = room_summary["total_hours"].sum() if not room_summary.empty else 0.0
    most_used_room = room_summary.iloc[0]["room"] if not room_summary.empty else "N/A"
    least_used_room = room_summary.iloc[-1]["room"] if not room_summary.empty else "N/A"
    most_active_user = user_summary.iloc[0]["user"] if not user_summary.empty else "N/A"

    st.markdown("##### Key metrics")
    metrics = {
        "Total bookings": total_bookings,
        "Total booked hours": total_hours,
        "Most active user": most_active_user,
        "Most used room": most_used_room,
        "Least used room": least_used_room,
    }
    cols = st.columns(5)
    for col, (label, value) in zip(cols, metrics.items()):
        col.metric(label, value)

    st.markdown("##### Booking activity by user")
    if user_summary.empty:
        st.info("No bookings found in this period.")
    else:
        st.dataframe(user_summary, width="stretch")

    st.markdown("##### Room utilization and booking volumes")
    st.dataframe(room_summary, width="stretch")

    st.markdown("##### Bookings by weekday")
    if not weekday_summary.empty:
        st.dataframe(weekday_summary, width="stretch")


def admin_holidays(conn, user: dict) -> None:
    weekday_names = service.WEEKDAY_NAMES
    current_closed = service.get_closed_weekdays(conn)
    with st.form("weekly_closed_days"):
        st.markdown("#### Weekly Closed Days")
        selected_days = st.multiselect(
            "Closed every week",
            weekday_names,
            default=[weekday_names[index] for index in sorted(current_closed)],
            help="These days are hidden from the calendar and cannot be booked.",
        )
        save_closed_days = st.form_submit_button("Save weekly closed days")
    if save_closed_days:
        try:
            selected_indices = [weekday_names.index(day_name) for day_name in selected_days]
            service.set_closed_weekdays(conn, selected_indices, user)
            st.success("Weekly closed days saved.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.markdown("#### Date-Specific Holidays")
    with st.form("holiday"):
        holiday_date = st.date_input("Holiday date", date.today())
        name = st.text_input("Holiday name")
        submitted = st.form_submit_button("Save holiday")
    if submitted:
        try:
            service.upsert_holiday(conn, holiday_date, name or "Holiday", user)
            st.success("Holiday saved.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    for row in service.list_holidays(conn):
        c1, c2, c3 = st.columns([2, 4, 1])
        c1.write(row["holiday_date"])
        c2.write(row["name"])
        delete_key = f"confirm_delete_holiday_{row['id']}"
        if c3.button("Delete", key=f"holiday_{row['id']}"):
            st.session_state[delete_key] = True
            st.rerun()
        if st.session_state.get(delete_key):
            st.warning(f"Confirm delete holiday {row['holiday_date']} - {row['name']}. This cannot be undone.")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("Confirm delete", key=f"do_delete_holiday_{row['id']}"):
                service.delete_holiday(conn, int(row["id"]), user)
                st.session_state.pop(delete_key, None)
                st.success("Holiday deleted.")
                st.rerun()
            if cancel_col.button("Cancel delete", key=f"cancel_delete_holiday_{row['id']}"):
                st.session_state.pop(delete_key, None)
                st.rerun()



if __name__ == "__main__":
    main()
