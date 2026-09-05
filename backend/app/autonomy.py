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
