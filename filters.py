# filters.py

import re


def contains_link(text: str) -> bool:
    """Check if text contains any URL or Telegram link."""
    if not text:
        return False
    return bool(re.search(r"(https?://|www\.|t\.me/)\S+", text, re.IGNORECASE))


def apply_text_transform(text: str, replacements: list) -> str:
    """Apply find/replace rules to text."""
    for rep in replacements:
        find    = rep.get("find", "").strip()
        replace = rep.get("replace", "").strip()
        if not find:
            continue
        if find == "url":
            text = re.sub(r"https?://\S+", replace, text)
        elif find == "username":
            text = re.sub(r"@\w+", replace, text)
        else:
            text = text.replace(find, replace)
    return text


def apply_placeholders(text: str, sender: dict) -> str:
    """Replace [user.*] placeholders with actual sender info."""
    if not text:
        return text
    text = text.replace("[user.username]",   sender.get("username",   ""))
    text = text.replace("[user.id]",         sender.get("id",         ""))
    text = text.replace("[user.first_name]", sender.get("first_name", ""))
    text = text.replace("[user.last_name]",  sender.get("last_name",  ""))
    # Legacy [[Message.*]] aliases — auto convert
    text = re.sub(r"\[\[Message\.sender\.username\]\]",   sender.get("username",   ""), text)
    text = re.sub(r"\[\[Message\.sender\.id\]\]",         sender.get("id",         ""), text)
    text = re.sub(r"\[\[Message\.sender\.first_name\]\]", sender.get("first_name", ""), text)
    text = re.sub(r"\[\[Message\.sender\.last_name\]\]",  sender.get("last_name",  ""), text)
    return text
