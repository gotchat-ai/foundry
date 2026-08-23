import re

_ROLE_MARKER_RE = re.compile(r"\b(?:USER|ASSISTANT)\b\s*:?\s*")


def _strip_role_markers(text: str) -> str:
    if not text:
        return text
    return _ROLE_MARKER_RE.sub("", text)


def _strip_leading_user_echo(text: str, user_text: str) -> str:
    if not text or not user_text:
        return text
    lead = len(text) - len(text.lstrip())
    t = text[lead:]
    u = user_text.strip()
    if not u:
        return text
    if t.lower().startswith(u.lower()):
        return t[len(u):].lstrip()
    return text
