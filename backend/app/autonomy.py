LEVELS = (
    "proceed_silently",
    "proceed_and_notify",
    "ask_first",
    "escalate",
)

ACTIONS = ("archive", "label", "draft_reply", "unsubscribe", "none", "forward", "delete", "send")

SYSTEM_FLOORS = {
    "send": "ask_first",
    "draft_reply": "ask_first",
    "unsubscribe": "ask_first",
    "delete": "escalate",
    "forward": "escalate",
    "money": "escalate",
    "prompt_injection": "escalate",
}


def rank(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError:
        return LEVELS.index("ask_first")


def more_cautious(level: str, steps: int = 1) -> str:
    return LEVELS[min(rank(level) + steps, len(LEVELS) - 1)]


def less_cautious(level: str, steps: int = 1) -> str:
    return LEVELS[max(rank(level) - steps, 0)]


def max_level(a: str, b: str) -> str:
    return a if rank(a) >= rank(b) else b


def effective_preference_level(pref: dict) -> str:
    preferred = pref.get("preferred_autonomy") or "ask_first"
    if preferred not in LEVELS:
        preferred = "ask_first"
    if preferred != "proceed_silently":
        return preferred
    n = int(pref.get("sample_count") or 0)
    conf = float(pref.get("confidence") or 0)
    ptype = pref.get("pattern_type") or ""
    need = 3 if ptype == "sender_domain" else 5
    if n < need or conf < 0.7:
        return "proceed_and_notify"
    return preferred
