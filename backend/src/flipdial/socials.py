"""Social and messaging platforms: one name per platform, and links to profiles."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# key: (display name, profile URL with {h} for the handle, other names and hosts)
PLATFORMS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "instagram": ("Instagram", "https://instagram.com/{h}", ("ig", "insta", "instagram.com")),
    "facebook": ("Facebook", "https://facebook.com/{h}", ("fb", "facebook.com", "fb.com")),
    "x": ("X", "https://x.com/{h}", ("twitter", "x.com", "twitter.com", "tw")),
    "tiktok": ("TikTok", "https://tiktok.com/@{h}", ("tik tok", "tiktok.com")),
    "linkedin": ("LinkedIn", "https://linkedin.com/in/{h}", ("linked in", "linkedin.com")),
    "bluesky": ("Bluesky", "https://bsky.app/profile/{h}", ("bsky", "bsky.app", "bsky.social")),
    "threads": ("Threads", "https://threads.net/@{h}", ("threads.net",)),
    "mastodon": ("Mastodon", "", ("fediverse",)),
    "youtube": ("YouTube", "https://youtube.com/@{h}", ("yt", "youtube.com", "you tube")),
    "pinterest": ("Pinterest", "https://pinterest.com/{h}", ("pinterest.com",)),
    "behance": ("Behance", "https://behance.net/{h}", ("behance.net",)),
    "dribbble": ("Dribbble", "https://dribbble.com/{h}", ("dribbble.com",)),
    "etsy": ("Etsy", "https://etsy.com/shop/{h}", ("etsy.com",)),
    "github": ("GitHub", "https://github.com/{h}", ("github.com",)),
    "snapchat": ("Snapchat", "https://snapchat.com/add/{h}", ("snap", "snapchat.com")),
    "whatsapp": ("WhatsApp", "https://wa.me/{h}", ("whats app", "wa.me")),
    "signal": ("Signal", "", ()),
    "telegram": ("Telegram", "https://t.me/{h}", ("t.me",)),
}
_ALIASES = {
    alias: key
    for key, (name, _, aliases) in PLATFORMS.items()
    for alias in (key, name.lower(), *aliases)
}


def platform_key(name: str) -> str:
    """Canonical key for a platform name ("Twitter" -> "x"), or "" if unknown."""
    n = " ".join(name.strip().lower().split()).removeprefix("www.")
    return _ALIASES.get(n, "")


def split_url(value: str) -> tuple[str, str] | None:
    """(platform key, handle) for a profile link like instagram.com/name, else None."""
    v = value.strip()
    if "/" not in v or " " in v:
        return None
    u = urlparse(v if "://" in v else "https://" + v)
    key = platform_key((u.hostname or "").removeprefix("www.").removeprefix("m."))
    parts = [p for p in u.path.split("/") if p]
    if not key or not parts:
        return None
    if parts[0] in ("in", "company", "shop", "add", "profile") and len(parts) > 1:
        parts = parts[1:]
    return key, parts[0].lstrip("@")


def normalize(platform: str, handle: str) -> tuple[str, str]:
    """A consistent (platform display name, handle) pair."""
    handle = handle.strip()
    found = split_url(handle)
    key = platform_key(platform)
    if found and (not key or key == found[0]):
        key, handle = found
    if key == "whatsapp":
        handle = handle.lstrip("@")
    elif key != "mastodon":
        handle = handle.lstrip("@")
    name = PLATFORMS[key][0] if key else platform.strip()
    return name, handle


def profile_url(platform: str, handle: str) -> str:
    """A link to the profile, or "" when there isn't a reliable one."""
    key = platform_key(platform)
    h = handle.strip()
    if not key or not h:
        return ""
    if key == "mastodon":
        m = re.match(r"^@?([A-Za-z0-9_.]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})$", h)
        return f"https://{m[2]}/@{m[1]}" if m else ""
    if key == "whatsapp":
        digits = re.sub(r"\D", "", h)
        return f"https://wa.me/{digits}" if len(digits) >= 7 else ""
    template = PLATFORMS[key][1]
    if not template or not re.match(r"^[A-Za-z0-9_.\-]{1,60}$", h.lstrip("@")):
        return ""
    return template.format(h=h.lstrip("@"))
