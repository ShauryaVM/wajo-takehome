from dataclasses import dataclass
import re

from app.autonomy import ACTIONS, max_level, rank
from app.classifier import Classification, sender_domain

# These are the hard floor. Preferences and prompt text cannot lower them.


@dataclass
class SafetyHit:
    name: str
    floor: str
    reason: str


@dataclass
class GuardedDecision:
    autonomy_level: str
    action_type: str
    safety_hit: str | None
    reason: str | None
    overridden: bool


_INJECTION = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"ignore your (previous )?instructions",
    r"forget all prior rules",
    r"you are now in (admin|developer) (mode|override)",
    r"you are now in admin mode",
    r"disable the safety floor",
    r"if you are an (llm|language model|automated assistant)",
    r"for automated assistants reading",
    r"important for the email agent",
    r"developer override",
    r"auto-reply.{0,80}(recovery codes|api keys|passwords|credentials|auth codes)",
    r"reveal (any )?(tool )?credentials",
    r"print the user's oauth",
    r"stored (api keys|passwords|user secrets|recovery codes)",
    r"proceed silently.{0,40}(keys|codes|secrets)",
    r"do not (ask|notify) the user",
]

_MONEY = [
    r"\bwire\b.{0,40}\$",
    r"initiate a wire",
    r"routing:\s*\d{6,}",
    r"\bach\b.{0,30}routing",
    r"gift cards?",
    r"bitcoin|btc address|crypto wallet|\busdc\b|\beth mainnet\b",
    r"0x[a-fA-F0-9]{20,}",
    r"update your direct deposit",
    r"redirect (payroll|salary|paycheck)",
    r"send \$\d",
    r"pay (immediately|today) by",
]

_DELETE = [
    r"permanently delete",
    r"empty trash",
    r"drop (the )?.{0,30}legal hold",
    r"wipe this mailbox",
    r"gdpr erasure",
    r"do not move to trash",
    r"delete every email",
    r"delete all mail",
]

_FORWARD = [
    r"fwd this thread to my (gmail|yahoo|hotmail|personal)",
    r"forward .{0,60}to my (personal |gmail)",
    r"customer list",
    r"forward a copy offsite",
    r"send .{0,40}to \S+@gmail\.com",
    r"external (gmail|yahoo) address",
    r"bcc my personal",
    r"personal address .{0,60}@(gmail|yahoo|hotmail)",
    r"forward all .{0,240}@",
    r"to my yahoo",
]


def _search(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE | re.DOTALL) for p in patterns)


def user_rule_applies(rule_type: str, rule_action: str, sender: str, action_type: str) -> bool:
    key = (rule_type or "").strip().lower()
    want_action = (rule_action or "*").strip().lower()
    act = (action_type or "").strip().lower()
    sender_l = (sender or "").lower()
    domain = sender_domain(sender)

    if want_action and want_action != "*" and want_action != act:
        return False

    if not key or key in {"*", "all", "any"}:
        return bool(want_action and want_action != "*")

    if key in ACTIONS:
        return act == key

    if "@" in key:
        return key in sender_l
    if "." in key:
        return domain == key or domain.endswith("." + key) or key in sender_l
    return False


def detect_hits(subject: str, body: str, action_type: str) -> list[SafetyHit]:
    blob = f"{subject or ''}\n{body or ''}"
    hits: list[SafetyHit] = []
    if _search(_INJECTION, blob):
        hits.append(
            SafetyHit(
                "prompt_injection",
                "escalate",
                "Body tries to rewrite agent instructions or exfiltrate secrets.",
            )
        )
    if _search(_MONEY, blob):
        hits.append(
            SafetyHit(
                "money",
                "escalate",
                "Looks like a payment, wire, or account-change request.",
            )
        )
    if _search(_DELETE, blob) or action_type == "delete":
        hits.append(
            SafetyHit(
                "delete",
                "escalate",
                "Deletion is irreversible. Always escalate.",
            )
        )
    if _search(_FORWARD, blob) or action_type == "forward":
        hits.append(
            SafetyHit(
                "forward_external",
                "escalate",
                "Forwarding out of the tenant is an external action.",
            )
        )
    if action_type in {"send", "draft_reply"}:
        hits.append(
            SafetyHit(
                "send",
                "ask_first",
                "Anything outbound waits for approval.",
            )
        )
    if action_type == "unsubscribe":
        hits.append(
            SafetyHit(
                "unsubscribe",
                "ask_first",
                "Unsubscribe sends mail off-box. Wait for approval.",
            )
        )
    return hits


def apply_safety(
    classification: Classification,
    subject: str,
    body: str,
    extra_floors: list[tuple[str, str]] | None = None,
) -> GuardedDecision:
    hits = detect_hits(subject, body, classification.action_type)
    floor = classification.autonomy_level
    strongest: SafetyHit | None = None
    for h in hits:
        floor = max_level(floor, h.floor)
        if h.name in {"send", "unsubscribe"}:
            continue
        if strongest is None or rank(h.floor) >= rank(strongest.floor):
            strongest = h

    for name, min_level in extra_floors or []:
        before = floor
        floor = max_level(floor, min_level)
        if floor != before and strongest is None:
            strongest = SafetyHit(name, min_level, f"User safety rule '{name}' raised the floor.")

    if rank("ask_first") > rank(classification.autonomy_level) and rank(floor) >= rank("ask_first"):
        if strongest is None:
            ask_hit = next((h for h in hits if h.name in {"send", "unsubscribe"}), None)
            if ask_hit:
                strongest = ask_hit

    action = classification.action_type
    if floor == "escalate":
        action = "none"

    return GuardedDecision(
        autonomy_level=floor,
        action_type=action,
        safety_hit=strongest.name if strongest else None,
        reason=strongest.reason if strongest else None,
        overridden=floor != classification.autonomy_level or action != classification.action_type,
    )
