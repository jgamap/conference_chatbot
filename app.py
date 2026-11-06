from pathlib import Path
import hmac

import streamlit as st
from openai import (
    OpenAI,
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import BaseModel


# ---------- App settings ----------

st.set_page_config(
    page_title="Agent Instruction Builder",
    page_icon="🛠️",
    layout="centered",
)

MAX_TURNS = 25
MAX_MESSAGE_LENGTH = 4000

OPENING_MESSAGE = (
    "Let's turn your idea into clear agent instructions. "
    "We will define the task, inputs, output, and what success looks like.\n\n"
    "**What would you like your agent to help someone do?**"
)


# ---------- Structured response ----------

class AgentBrief(BaseModel):
    idea: str
    task: str
    inputs: str
    output: str
    success: str


class CoachResponse(BaseModel):
    reply: str
    brief: AgentBrief
    draft_markdown: str


# ---------- Configuration ----------

try:
    api_key = st.secrets["OPENAI_API_KEY"]
    model = st.secrets.get("OPENAI_MODEL", "gpt-5.4-mini")
    workshop_code = st.secrets["WORKSHOP_CODE"]
except (FileNotFoundError, KeyError):
    st.error(
        "Add OPENAI_API_KEY and WORKSHOP_CODE to "
        ".streamlit/secrets.toml, then restart the app."
    )
    st.stop()

if not api_key.strip() or not workshop_code.strip():
    st.error("The API key and workshop access code must not be empty.")
    st.stop()

prompt_path = Path(__file__).with_name("instructions.md")

if not prompt_path.exists():
    st.error("Create instructions.md beside app.py.")
    st.stop()

coach_instructions = prompt_path.read_text(encoding="utf-8")


# ---------- Workshop access ----------

if not st.session_state.get("authenticated", False):
    st.title("🛠️ Agent Instruction Builder")

    with st.form("access_form"):
        entered_code = st.text_input(
            "Workshop access code",
            type="password",
        )
        submitted = st.form_submit_button("Enter")

    if submitted:
        valid = hmac.compare_digest(
            entered_code.encode("utf-8"),
            workshop_code.encode("utf-8"),
        )

        if valid:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("That access code does not match.")

    st.stop()


# ---------- Session state ----------

if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": OPENING_MESSAGE}
    ]
    st.session_state.api_history = []
    st.session_state.brief = {
        "idea": "",
        "task": "",
        "inputs": "",
        "output": "",
        "success": "",
    }
    st.session_state.draft = ""
    st.session_state.turns = 0


# ---------- Interface ----------

st.title("🛠️ Agent Instruction Builder")
st.write("Develop your idea, then create instructions you can edit and test.")

st.caption(
    "Your messages are sent to OpenAI to generate responses. "
    "Use fictional examples and non-sensitive descriptions."
)

with st.sidebar:
    st.header("Your agent brief")

    field_labels = {
        "idea": "💡 Idea",
        "task": "🎯 Task",
        "inputs": "📥 Inputs",
        "output": "📤 Output",
        "success": "✅ Success",
    }

    for field, label in field_labels.items():
        st.markdown(f"**{label}**")
        st.write(
            st.session_state.brief[field]
            or "Not defined yet"
        )

    st.caption(
        f"{st.session_state.turns} of {MAX_TURNS} messages used."
    )

    if st.button("Start a new conversation"):
        for key in (
            "messages",
            "api_history",
            "brief",
            "draft",
            "turns",
        ):
            st.session_state.pop(key, None)

        st.rerun()


# ---------- Conversation ----------

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

limit_reached = st.session_state.turns >= MAX_TURNS

if limit_reached:
    st.info(
        "This conversation has reached its message limit. "
        "You can still copy or download your draft."
    )

user_message = st.chat_input(
    "Describe your idea, answer a question, or request a revision…",
    max_chars=MAX_MESSAGE_LENGTH,
    disabled=limit_reached,
)

if user_message and user_message.strip():
    with st.chat_message("user"):
        st.markdown(user_message)

    request_history = [
        *st.session_state.api_history,
        {"role": "user", "content": user_message},
    ]

    try:
        with st.spinner("Preparing the next step…"):
            client = OpenAI(
                api_key=api_key,
                timeout=60.0,
                max_retries=0,
            )

            response = client.responses.parse(
                model=model,
                instructions=coach_instructions,
                input=request_history,
                text_format=CoachResponse,
                max_output_tokens=3500,
                store=False,
            )

            result = response.output_parsed

            if result is None:
                raise ValueError("No usable structured response.")

    except AuthenticationError:
        st.error("The API key was rejected. Ask the organiser to check it.")

    except RateLimitError:
        st.error(
            "The API is temporarily limited or its allowance is exhausted. "
            "Wait before retrying, or ask the organiser to check usage."
        )

    except APIConnectionError:
        st.error("Could not reach OpenAI. Check the connection and try again.")

    except APIStatusError:
        st.error(
            "OpenAI could not complete the request. "
            "Ask the organiser to check model access and service status."
        )

    except Exception:
        st.error(
            "The reply could not be completed or read. "
            "Your previous conversation and draft are unchanged. "
            "Please resend your message."
        )

    else:
        st.session_state.messages.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": result.reply},
        ])

        # Preserve the complete structured response for future turns.
        st.session_state.api_history = [
            *request_history,
            {
                "role": "assistant",
                "content": result.model_dump_json(),
            },
        ]

        st.session_state.brief = result.brief.model_dump()
        st.session_state.draft = result.draft_markdown
        st.session_state.turns += 1

        st.rerun()


# ---------- Copyable and downloadable draft ----------

if st.session_state.draft:
    st.divider()
    st.subheader("Your agent instructions")

    st.caption(
        "Use the copy icon in the block below, or download the Markdown file. "
        "Request changes in the chat."
    )

    st.code(
        st.session_state.draft,
        language="markdown",
        wrap_lines=True,
    )

    st.download_button(
        label="Download instructions (.md)",
        data=st.session_state.draft,
        file_name="agent-instructions.md",
        mime="text/markdown",
    )