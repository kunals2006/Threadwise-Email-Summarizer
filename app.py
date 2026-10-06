import hashlib
import html
import json
import os
import csv
from io import BytesIO
from io import StringIO
from email import policy
from email.parser import BytesParser

import streamlit as st

from summarizer import format_for_download, summarize_thread


def app_setting(name, default=""):
    """Read a setting from Streamlit secrets or environment without exposing it."""
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return value or os.getenv(name, default)


st.set_page_config(
    page_title="Threadwise | Email intelligence",
    page_icon="✉️",
    layout="wide",
    initial_sidebar_state="expanded",
)


SAMPLE_THREAD = """From: Aisha Khan <aisha@example.com>
Date: Tuesday, 9:14 AM
Subject: Website launch plan

Hi team,
We are planning to launch the new website next Tuesday. The original date was June 12, but we need the final product images before the release.

From: Aisha Khan <aisha@example.com>
Date: Tuesday, 10:02 AM

I will send the final images by Thursday at 3 PM. Rohan, could you please confirm the testing schedule?

From: Rohan Mehta <rohan@example.com>
Date: Tuesday, 10:30 AM

Confirmed. I will finish testing by Monday afternoon. We should move the launch to Tuesday so there is time to fix any issues.

From: Aisha Khan <aisha@example.com>
Date: Tuesday, 10:45 AM

Agreed, Tuesday works. Please share any blockers by tomorrow noon. Does everyone agree with this plan?"""


def load_sample():
    st.session_state["thread_text"] = SAMPLE_THREAD
    st.session_state["summary_result"] = None


def clear_thread():
    st.session_state["thread_text"] = ""
    st.session_state["summary_result"] = None


def read_email_file(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    filename = uploaded_file.name.lower()
    if filename.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(file_bytes))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ValueError("No selectable text found. Scanned PDFs need OCR before upload.")
        return text
    if filename.endswith(".eml"):
        message = BytesParser(policy=policy.default).parsebytes(file_bytes)
        headers = []
        if message.get("subject"):
            headers.append(f"Subject: {message.get('subject')}")
        if message.get("from"):
            headers.append(f"From: {message.get('from')}")

        body_parts = []
        for part in message.walk():
            if part.get_content_type() != "text/plain":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            try:
                body = part.get_content()
            except (LookupError, UnicodeDecodeError):
                continue
            if isinstance(body, str) and body.strip():
                body_parts.append(body.strip())
        return "\n".join(headers) + "\n\n" + "\n\n".join(body_parts)

    return file_bytes.decode("utf-8-sig", errors="replace")


def make_reply_draft(summary, tone):
    openings = {
        "Professional": "Hello everyone,\n\nThank you for the updates. Here is my understanding:",
        "Friendly": "Hi everyone,\n\nThanks for the updates! Here is what I took away:",
        "Direct": "Hi,\n\nMy understanding of the thread:",
    }
    points = summary["key_points"][:3]
    bullet_points = "\n".join(f"- {point}" for point in points)
    return (
        f"{openings[tone]}\n\n{bullet_points}\n\n"
        "Please let me know if I missed anything.\n\n"
        "Best,\n[Your name]"
    )


if "thread_text" not in st.session_state:
    st.session_state["thread_text"] = ""
if "summary_result" not in st.session_state:
    st.session_state["summary_result"] = None
if "brief_history" not in st.session_state:
    st.session_state["brief_history"] = []


st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(ellipse at 80% 0%, rgba(61, 91, 145, .25), transparent 35%),
            radial-gradient(ellipse at 0% 100%, rgba(26, 46, 78, .2), transparent 38%),
            #080f1b;
        color: #e8edf6;
    }
    .block-container { max-width: 1320px; padding-top: 2.3rem; padding-bottom: 2.8rem; }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0e1929, #0a1422);
        border-right: 1px solid #263952;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(145deg, rgba(19, 32, 51, .98), rgba(13, 24, 40, .98));
        border: 1px solid #293d59;
        border-radius: 18px;
        box-shadow: 0 18px 46px rgba(0, 0, 0, .2);
        padding: 9px;
    }
    div[data-testid="stTextArea"] textarea {
        background: #0b1524;
        color: #e8edf6;
        border: 1px solid #2b3e59;
        border-radius: 13px;
        line-height: 1.7;
    }
    div[data-testid="stTextArea"] textarea:focus {
        border-color: #829fda;
        box-shadow: 0 0 0 2px rgba(130, 159, 218, .18);
    }
    div.stButton > button, div[data-testid="stDownloadButton"] button {
        min-height: 42px;
        border-radius: 11px;
        border: 1px solid #344a69;
        font-weight: 600;
        transition: all 150ms ease;
    }
    div.stButton > button[kind="primary"] {
        background: linear-gradient(110deg, #7897d1, #a2b9e7);
        border: 0;
        color: #0b1422;
        box-shadow: 0 8px 22px rgba(83, 117, 177, .22);
    }
    div.stButton > button[kind="primary"]:hover { background: #b5c8ed; border: 0; }
    .eyebrow {
        display: inline-block;
        color: #c3d1ed;
        background: rgba(95, 126, 184, .13);
        border: 1px solid rgba(125, 154, 204, .3);
        border-radius: 30px;
        padding: 6px 11px;
        font-size: .7rem;
        font-weight: 700;
        letter-spacing: .13em;
        margin-bottom: .65rem;
    }
    .hero-title {
        color: #f3f6fc;
        font-size: clamp(2.2rem, 4vw, 3.25rem);
        font-weight: 750;
        letter-spacing: -.055em;
        line-height: 1.05;
        margin: .35rem 0 .75rem;
    }
    .helper-text { color: #aab8ce; font-size: 1rem; line-height: 1.65; }
    .hero-subtitle { max-width: 760px; color: #aab8ce; font-size: 1.08rem; line-height: 1.7; }
    .hero-proof { color: #c5d2e8; font-size: .78rem; letter-spacing: .03em; }
    .step-label { color: #9db6e6; font-size: .72rem; font-weight: 700; letter-spacing: .12em; }
    .step-title { color: #edf2fb; font-size: 1.08rem; font-weight: 650; margin: .3rem 0; }
    .privacy-note {
        background: #111f32;
        border: 1px solid #2b3d57;
        border-radius: 13px;
        padding: 13px 14px;
        color: #bbc8dc;
        font-size: .84rem;
        line-height: 1.6;
    }
    h1 { color: #f0f4fb; letter-spacing: -.045em; }
    h2, h3, h4 { color: #e9eef7; }
    [data-testid="stMetric"] {
        background: #0c1727;
        border: 1px solid #263951;
        border-radius: 12px;
        padding: 10px 13px;
    }
    hr { border-color: #263951; }
    </style>
    """,
    unsafe_allow_html=True,
)


with st.sidebar:
    st.markdown("## ✉️ Threadwise")
    st.caption("Long threads. Clear next steps.")
    with st.expander("About Threadwise"):
        st.write(
            "Threadwise is an email-thread intelligence project that turns long conversations "
            "into a concise brief, a follow-up board, and an editable reply starter."
        )
        st.markdown("**Built with**  ")
        st.caption("Python · Streamlit · TF-IDF · OpenAI Responses API (optional)")
        st.markdown("**How it works**  ")
        st.caption("Local mode ranks original sentences on your computer. AI mode is optional and sends the thread to OpenAI only after consent.")
        st.markdown("**Review before acting**  ")
        st.caption("Owners, deadlines, tone, and urgency can be estimates. Verify important details in the original email.")
    st.divider()
    st.markdown("### Brief settings")
    engine = st.selectbox("Summarizer", ["Local NLP (offline)", "OpenAI AI (API)"], index=0)
    summary_length = st.selectbox("Detail level", ["Short", "Balanced", "Detailed"], index=1)
    focus = st.selectbox("Prioritize", ["Balanced", "Decisions", "Action items"], index=0)
    reply_tone = st.selectbox("Reply draft tone", ["Professional", "Friendly", "Direct"])
    api_key = app_setting("OPENAI_API_KEY")
    model_name = app_setting("OPENAI_MODEL", "gpt-5-mini")
    consent = False
    if engine.startswith("OpenAI"):
        model_name = st.text_input("Model", value=model_name, help="Defaults to gpt-5-mini.")
        st.warning("AI mode sends the email text to OpenAI's API. API usage may incur charges; check your provider account.")
        consent = st.checkbox("I agree to send this email thread to the OpenAI API.")
        if not api_key:
            st.caption("Add OPENAI_API_KEY to .streamlit/secrets.toml or your environment to enable AI mode.")
    st.divider()
    st.markdown(
        '<div class="privacy-note">🔒 <b>Local mode is private by default</b><br>'
        'Local NLP runs on this computer. AI mode only runs after you select it and consent.</div>',
        unsafe_allow_html=True,
    )


st.markdown('<div class="eyebrow">✦ EMAIL THREAD INTELLIGENCE · LOCAL BY DEFAULT</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-title">Make the long thread short.</div>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-subtitle">Turn a crowded email conversation into the details that matter: '
    'decisions, follow-ups, open questions, and a reply you can edit.</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="hero-proof">PRIVATE LOCAL MODE &nbsp;·&nbsp; OPTIONAL AI &nbsp;·&nbsp; EXPORT-READY BRIEFS</p>',
    unsafe_allow_html=True,
)

input_column, output_column = st.columns([1.02, 0.98], gap="large")

with input_column:
    with st.container(border=True):
        st.subheader("Email thread")
        st.caption("Paste a conversation or load a .txt, .eml, or text-based .pdf file.")

        sample_col, clear_col = st.columns(2)
        sample_col.button("✦ Try sample thread", use_container_width=True, on_click=load_sample)
        clear_col.button("Clear", use_container_width=True, on_click=clear_thread)

        uploaded_file = st.file_uploader(
            "Upload an email file",
            type=["txt", "eml", "pdf"],
            help="PDFs must contain selectable text; scanned image PDFs need OCR first.",
        )
        load_file_col, file_hint_col = st.columns([1, 1.5])
        load_file_clicked = load_file_col.button(
            "Load uploaded file",
            use_container_width=True,
            disabled=uploaded_file is None,
        )
        file_hint_col.caption("Files are read locally.")

        if load_file_clicked and uploaded_file is not None:
            try:
                st.session_state["thread_text"] = read_email_file(uploaded_file)
                st.session_state["summary_result"] = None
                st.rerun()
            except Exception as error:
                st.error(f"Couldn't read that file: {error}")

        email_text = st.text_area(
            "Email conversation",
            key="thread_text",
            height=300,
            max_chars=50000,
            placeholder="Paste the complete email conversation here...",
            label_visibility="collapsed",
        )
        word_count = len(email_text.split())
        reading_time = max(1, round(word_count / 200)) if word_count else 0
        st.caption(
            f"{word_count:,} words"
            + (f" · about {reading_time} min read" if word_count else " · ready for your thread")
        )

        summarize_clicked = st.button("Build thread brief  →", type="primary", use_container_width=True)
        if summarize_clicked:
            if not email_text.strip():
                st.warning("Paste a thread, load a file, or try the sample first.")
            else:
                points_by_length = {"Short": 2, "Balanced": 4, "Detailed": 7}
                with st.spinner("Reading the thread and finding the useful signals..."):
                    try:
                        if engine.startswith("OpenAI"):
                            if not api_key:
                                raise ValueError("Add OPENAI_API_KEY before selecting AI mode.")
                            if not consent:
                                raise ValueError("Please confirm API sharing in the sidebar first.")
                            from ai_summarizer import summarize_with_openai

                            result = summarize_with_openai(
                                email_text, api_key, model=model_name.strip() or "gpt-5-mini",
                                key_point_limit=points_by_length[summary_length], focus=focus, tone=reply_tone,
                            )
                        else:
                            result = summarize_thread(
                                email_text,
                                key_point_limit=points_by_length[summary_length],
                                focus=focus,
                            )
                            result["summary"] = "Local mode selects the most relevant original sentences; it does not generate new prose."
                            result["engine"] = "Local TF-IDF + rules"
                            result["reply_draft"] = ""
                        st.session_state["summary_result"] = result
                        st.session_state["brief_history"].insert(0, {
                            "subject": result["subject"], "engine": result["engine"],
                            "key_points": result["key_points"][:3],
                        })
                        st.session_state["brief_history"] = st.session_state["brief_history"][:8]
                    except Exception as error:
                        error_code = str(getattr(error, "code", "") or "").lower()
                        error_details = str(error).lower()
                        if (
                            error_code in {"insufficient_quota", "credit_balance_exhausted"}
                            or "credit_balance_exhausted" in error_details
                            or "no credits remaining" in error_details
                        ):
                            st.error(
                                "OpenAI received the request, but this API account has no credits available. "
                                "Choose Local NLP (offline) to keep using the summarizer now, or add API credits "
                                "in your OpenAI billing settings to use AI mode."
                            )
                            st.link_button(
                                "Open API billing settings",
                                "https://platform.openai.com/settings/organization/billing",
                            )
                        elif getattr(error, "status_code", None) == 401 or error_code in {"invalid_api_key", "authentication_error"}:
                            st.error(
                                "OpenAI rejected the API key. Check that the key is current and belongs to a project "
                                "with API access, then update .streamlit/secrets.toml and restart Threadwise."
                            )
                        else:
                            st.error(f"Couldn't build the brief: {error}")

with output_column:
    with st.container(border=True):
        st.subheader("Thread brief")
        summary = st.session_state.get("summary_result")

        if not summary:
            st.markdown("### A clear brief is one click away")
            st.caption("Results will include the conversation's main points and follow-ups.")
            st.markdown("#### ✦ Key points")
            st.caption("Important details ranked by TF-IDF relevance")
            st.markdown("#### ◈ Action board")
            st.caption("Tasks with likely owner and deadline cues")
            st.markdown("#### ⌁ Thread insights")
            st.caption("Topics, urgency signals, and tone estimate")
        else:
            st.caption(f"Generated with {summary.get('engine', 'Local NLP')}")
            signature = hashlib.sha1(
                (summary["subject"] + "|" + "|".join(summary["key_points"][:2]) + reply_tone).encode("utf-8")
            ).hexdigest()[:12]
            reply_state_key = f"reply_draft_{signature}"

            st.markdown(f"#### {html.escape(summary['subject'])}")
            names = " · ".join(summary["participants"]) or "Participants not detected"
            st.caption(f"{html.escape(names)} · {summary['message_count']} messages")

            overview_tab, actions_tab, insights_tab, reply_tab, export_tab = st.tabs(
                ["Overview", "Action board", "Insights", "Reply draft", "Export"]
            )

            with overview_tab:
                st.markdown("#### Summary approach" if summary.get("engine", "").startswith("Local") else "#### In a sentence")
                st.write(summary.get("summary", ""))
                metric_columns = st.columns(4)
                metric_columns[0].metric("Urgency", summary["urgency"])
                metric_columns[1].metric("Tone cue", summary["tone"])
                metric_columns[2].metric("Messages", summary["message_count"])
                metric_columns[3].metric("Action items", len(summary["actions"]))

                st.markdown("#### ✦ Key points")
                for point in summary["key_points"]:
                    st.markdown(f"- {html.escape(point)}")

                st.markdown("#### ◈ Decisions and status")
                for decision in summary["decisions"]:
                    st.markdown(f"- {html.escape(decision)}")

                st.markdown("#### ? Open questions")
                for question in summary["questions"]:
                    st.markdown(f"- {html.escape(question)}")

                st.markdown("#### ⚑ Risks and blockers")
                for risk in summary.get("risks", []):
                    st.markdown(f"- {html.escape(risk)}")

            with actions_tab:
                st.markdown("#### Follow-up tracker")
                st.caption("Owner and deadline are inferred from wording. Review before relying on them.")
                st.dataframe(summary["actions"], hide_index=True, use_container_width=True)

            with insights_tab:
                st.markdown("#### Thread signals")
                st.info(summary["urgency_reason"])
                st.markdown(f"**Tone estimate:** {summary['tone']}")
                st.caption(summary["tone_note"])
                st.markdown("**Topic keywords**")
                st.write(" · ".join(summary["topics"]) if summary["topics"] else "No topics detected")
                st.markdown("**Risks and blockers**")
                for risk in summary.get("risks", []):
                    st.markdown(f"- {html.escape(risk)}")
                st.markdown("**Text profile**")
                st.write(
                    f"{summary['word_count']:,} words · {summary['sentence_count']} sentences · "
                    f"{summary['message_count']} detected messages"
                )
                with st.expander("How the ranking works"):
                    st.write(
                        "The app ranks sentences with TF-IDF: terms that occur often in one sentence "
                        "but less often across the thread carry more weight. Decision and action phrases "
                        "receive a small explainable boost. This is extractive NLP, not a generative AI model."
                    )
                    st.latex(r"\mathrm{TFIDF}(t,s)=\mathrm{TF}(t,s)\times\log\frac{N+1}{\mathrm{DF}(t)+1}+1")

            with reply_tab:
                st.markdown("#### Editable reply starter")
                st.caption("A neutral template based on the key points; review and edit before sending.")
                if reply_state_key not in st.session_state:
                    st.session_state[reply_state_key] = summary.get("reply_draft") or make_reply_draft(summary, reply_tone)
                reply_text = st.text_area(
                    "Reply draft",
                    key=reply_state_key,
                    height=230,
                    label_visibility="collapsed",
                )
                st.download_button(
                    "Download reply draft",
                    data=reply_text,
                    file_name="threadwise-reply-draft.txt",
                    mime="text/plain",
                    use_container_width=True,
                )

            with export_tab:
                st.markdown("#### Take your brief with you")
                text_export = format_for_download(summary)
                json_export = json.dumps(summary, indent=2, ensure_ascii=False)
                csv_buffer = StringIO()
                action_writer = csv.DictWriter(csv_buffer, fieldnames=["Owner", "Action", "Deadline"])
                action_writer.writeheader()
                action_writer.writerows(summary["actions"])
                download_text_col, download_json_col, download_csv_col = st.columns(3)
                download_text_col.download_button(
                    "Download .txt",
                    data=text_export,
                    file_name="threadwise-brief.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
                download_json_col.download_button(
                    "Download .json",
                    data=json_export,
                    file_name="threadwise-brief.json",
                    mime="application/json",
                    use_container_width=True,
                )
                download_csv_col.download_button(
                    "Download actions .csv",
                    data=csv_buffer.getvalue(),
                    file_name="threadwise-actions.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

    with st.expander("Recent briefs (this session only)"):
        history = st.session_state["brief_history"]
        if history:
            st.caption("Only brief results are kept in memory until this app session ends; source email is not saved here.")
            for item in history:
                st.markdown(f"**{html.escape(item['subject'])}** · {html.escape(item['engine'])}")
                for point in item["key_points"]:
                    st.caption(f"• {point}")
            if st.button("Clear recent briefs"):
                st.session_state["brief_history"] = []
                st.rerun()
        else:
            st.caption("Your completed briefs will appear here.")

st.divider()
st.markdown("### A simple flow from thread to follow-up")
step_columns = st.columns(3, gap="medium")
steps = [
    ("01 · ADD CONTEXT", "Paste or upload", "Bring a conversation in as text, .eml, or a text-based PDF."),
    ("02 · FIND THE SIGNAL", "Review the brief", "See key points, decisions, action owners, questions, and risks."),
    ("03 · MOVE FORWARD", "Export or reply", "Edit a reply draft and download the brief or action list."),
]
for column, (label, title, description) in zip(step_columns, steps):
    with column:
        with st.container(border=True):
            st.markdown(f'<div class="step-label">{label}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="step-title">{title}</div>', unsafe_allow_html=True)
            st.caption(description)
st.caption("Threadwise · Built with Python and Streamlit · Local NLP or opt-in AI · Verify decisions and deadlines in the original email.")
