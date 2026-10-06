"""Explainable, local NLP helpers for Threadwise."""

import math
import re
from collections import Counter


STOP_WORDS = set(
    """
    a about above after again all also am an and any are as at be because been
    before being below between both but by can could did do does doing down
    during each few for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just me more
    most my myself no nor not of off on once only or other our ours ourselves
    out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up
    very was we were what when where which while who whom why will with you
    your yours yourself yourselves
    """.split()
)

ACTION_WORDS = re.compile(
    r"\b(will|must|should|need to|needs to|please|follow up|action required)\b",
    re.IGNORECASE,
)
DECISION_WORDS = re.compile(
    r"\b(agreed|confirmed|decided|approved|decision|we will go with|"
    r"works for me|moving forward|the plan is)\b",
    re.IGNORECASE,
)
URGENT_WORDS = re.compile(
    r"\b(urgent|asap|immediately|overdue|critical|blocking|time-sensitive)\b",
    re.IGNORECASE,
)
DEADLINE_WORDS = re.compile(
    r"\b(deadline|due by|by today|by tomorrow|end of day|eod|by (?:monday|tuesday|wednesday|thursday|friday))\b",
    re.IGNORECASE,
)
RISK_WORDS = re.compile(r"\b(blocker|blocked|risk|delay|issue|concern|dependency|at risk)\b", re.IGNORECASE)
POSITIVE_WORDS = set("agree agreed approved great good thanks appreciate excellent confirmed works helpful".split())
NEGATIVE_WORDS = set("issue problem concern concerned blocked blocker delay risk urgent unhappy fail".split())
TOPIC_FILTER = set(
    "please agreed agree confirmed confirm thanks thank hello team hi yes okay works "
    "moving forward could would shall thread email update updates regards best".split()
)
def _split_messages(thread):
    parts = re.split(r"(?=^From:\s*)", thread, flags=re.IGNORECASE | re.MULTILINE)
    return [part.strip() for part in parts if part.strip()] or [thread.strip()]


def _sender(message):
    match = re.search(r"^From:\s*([^<\n]+)", message, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_sentences(thread):
    sentence_rows = []
    for message in _split_messages(thread):
        sender = _sender(message)
        body_lines = []
        for line in message.splitlines():
            line = line.strip()
            if not line or line.startswith(">"):
                continue
            if re.match(r"^(from|to|cc|date|sent|subject):", line, re.IGNORECASE):
                continue
            body_lines.append(line)

        text = " ".join(body_lines)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            sentence = re.sub(r"\s+", " ", sentence).strip(" \t\r\n-•")
            if len(sentence) < 20:
                continue
            if re.match(r"^(hi|hello|thanks|thank you|best|regards)\b", sentence, re.IGNORECASE):
                continue
            if any(row["sentence"].casefold() == sentence.casefold() for row in sentence_rows):
                continue
            sentence_rows.append({"sentence": sentence, "sender": sender})
    return sentence_rows


def _tokens(text):
    return [
        word.casefold()
        for word in re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
        if word.casefold() not in STOP_WORDS and len(word) > 2
    ]


def _build_tfidf(sentence_rows):
    documents = [_tokens(row["sentence"]) for row in sentence_rows]
    document_frequency = Counter(
        token for document in documents for token in set(document)
    )
    total_documents = max(len(documents), 1)
    idf = {
        token: math.log((1 + total_documents) / (1 + count)) + 1
        for token, count in document_frequency.items()
    }

    sentence_vectors = []
    corpus_weights = Counter()
    for document in documents:
        counts = Counter(document)
        token_count = max(len(document), 1)
        vector = {
            token: (count / token_count) * idf[token]
            for token, count in counts.items()
        }
        sentence_vectors.append(vector)
        for token, weight in vector.items():
            corpus_weights[token] += weight

    return sentence_vectors, corpus_weights


def _sentence_score(sentence, vector, focus):
    score = sum(vector.values()) / max(len(vector), 1)
    if ACTION_WORDS.search(sentence):
        score += 0.45
    if DECISION_WORDS.search(sentence):
        score += 0.55
    if focus == "Decisions" and DECISION_WORDS.search(sentence):
        score += 1.2
    elif focus == "Action items" and ACTION_WORDS.search(sentence):
        score += 1.2
    return score


def _action_record(sentence, sender):
    owner = "Unassigned"
    named_owner = re.match(
        r"^([A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)\s+(?:will|must|should|needs? to)\b",
        sentence,
    )
    addressed_owner = re.match(
        r"^([A-Z][\w'-]+),\s*(?:could you|can you|would you|please)\b",
        sentence,
    )
    if named_owner:
        owner = named_owner.group(1)
    elif addressed_owner:
        owner = addressed_owner.group(1)
    elif re.match(r"^(i|we)\b", sentence, re.IGNORECASE) and sender:
        owner = sender

    deadline_match = re.search(
        r"\b(?:by|before|due(?:\s+by)?)\s+((?:the\s+)?(?:end\s+of\s+day|eod|today|tomorrow|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
        r"(?:\s+(?:morning|afternoon|evening|noon|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?)",
        sentence,
        re.IGNORECASE,
    )
    deadline = deadline_match.group(1).strip() if deadline_match else "Not stated"
    return {"Owner": owner, "Action": sentence, "Deadline": deadline}


def summarize_thread(thread, key_point_limit=4, focus="Balanced"):
    """Build an explainable extractive brief locally; no external AI call is made."""
    if not isinstance(thread, str) or not thread.strip():
        raise ValueError("Paste an email thread before asking for a summary.")

    rows = _extract_sentences(thread)
    if not rows:
        rows = [{"sentence": "The thread does not contain enough message text to summarize.", "sender": ""}]

    sentence_vectors, corpus_weights = _build_tfidf(rows)
    ranked = sorted(
        range(len(rows)),
        key=lambda index: (
            -_sentence_score(rows[index]["sentence"], sentence_vectors[index], focus),
            index,
        ),
    )

    limit = max(2, min(int(key_point_limit), 7))
    selected_indices = sorted(ranked[:limit])
    key_points = [rows[index]["sentence"] for index in selected_indices]

    decisions = [
        row["sentence"] for row in rows if DECISION_WORDS.search(row["sentence"])
    ][:5] or ["No clear decision phrase was found."]

    actions = []
    seen_actions = set()
    for row in rows:
        if ACTION_WORDS.search(row["sentence"]):
            action = _action_record(row["sentence"], row["sender"])
            if action["Action"].casefold() not in seen_actions:
                actions.append(action)
                seen_actions.add(action["Action"].casefold())
    actions = actions[:8] or [{"Owner": "—", "Action": "No clear action item found.", "Deadline": "—"}]

    questions = [row["sentence"] for row in rows if "?" in row["sentence"]][:5]
    questions = questions or ["No open question was found."]
    risks = [row["sentence"] for row in rows if RISK_WORDS.search(row["sentence"])][:5]
    risks = risks or ["No explicit blocker or risk wording was found."]

    subject_match = re.search(r"^Subject:\s*(.+)$", thread, re.IGNORECASE | re.MULTILINE)
    subject = subject_match.group(1).strip() if subject_match else "Email thread summary"
    participants = list(dict.fromkeys(filter(None, (_sender(message) for message in _split_messages(thread)))))
    message_count = max(1, len(re.findall(r"^From:\s*", thread, re.IGNORECASE | re.MULTILINE)))

    if URGENT_WORDS.search(thread):
        urgency = "High"
        urgency_reason = "Urgency language detected in the thread."
    elif DEADLINE_WORDS.search(thread):
        urgency = "Time-sensitive"
        urgency_reason = "The thread mentions a deadline or near-term due date."
    else:
        urgency = "Standard"
        urgency_reason = "No explicit urgent wording or near-term deadline detected."

    all_tokens = _tokens(thread)
    tone_counts = Counter(all_tokens)
    positive_count = sum(tone_counts[word] for word in POSITIVE_WORDS)
    negative_count = sum(tone_counts[word] for word in NEGATIVE_WORDS)
    if negative_count > positive_count:
        tone = "Concerned"
    elif positive_count > negative_count:
        tone = "Positive"
    else:
        tone = "Neutral"

    topics = [
        word
        for word, _ in corpus_weights.most_common(24)
        if word not in TOPIC_FILTER
    ][:7]

    return {
        "subject": subject,
        "participants": participants,
        "message_count": message_count,
        "word_count": len(thread.split()),
        "sentence_count": len(rows),
        "urgency": urgency,
        "urgency_reason": urgency_reason,
        "tone": tone,
        "tone_note": "Tone is a simple word-cue estimate, not a reliable emotion detector.",
        "topics": topics,
        "risks": risks,
        "key_points": key_points,
        "decisions": decisions,
        "actions": actions,
        "questions": questions,
    }


def format_for_download(summary):
    sections = [
        ("THREAD", [summary["subject"], f"Urgency: {summary['urgency']}", f"Tone cue: {summary['tone']}"]),
        ("KEY POINTS", summary["key_points"]),
        ("DECISIONS", summary["decisions"]),
        (
            "ACTION ITEMS",
            [f"{item['Owner']} — {item['Action']} (Deadline: {item['Deadline']})" for item in summary["actions"]],
        ),
        ("OPEN QUESTIONS", summary["questions"]),
        ("RISKS AND BLOCKERS", summary["risks"]),
        ("TOPIC KEYWORDS", summary["topics"]),
    ]
    return "\n\n".join(
        title + "\n" + "\n".join(f"- {item}" for item in items)
        for title, items in sections
    )
