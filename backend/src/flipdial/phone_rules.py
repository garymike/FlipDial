"""Which contacts go to the phone book (docs/sync.md).

Off by default. The most specific choice wins: the contact's own On or Off, then a tag or
deck that is On, then one that is Off, then the Everything switch.
"""

from __future__ import annotations

from dataclasses import dataclass

from flipdial import db
from flipdial.config import Settings

EVERYTHING = "*"


@dataclass
class Rules:
    tags: dict[str, str]  # tag or deck name -> 'on' or 'off'
    everything: bool
    choices: dict[str, str]  # uid -> 'on' or 'off'


def enabled(settings: Settings) -> bool:
    return bool(settings.carddav_url and settings.phone_addressbook)


def load(settings: Settings) -> Rules:
    with db.session(settings.db_path) as conn:
        rules = {r["name"]: r["state"] for r in conn.execute("SELECT * FROM phone_rules")}
        choices = {r["uid"]: r["state"] for r in conn.execute("SELECT * FROM phone_choice")}
    everything = rules.pop(EVERYTHING, "off") == "on"
    return Rules(rules, everything, choices)


def decide(uid: str, categories: list[str], rules: Rules) -> tuple[bool, str]:
    """(on the phone?, why) for one contact."""
    choice = rules.choices.get(uid)
    if choice:
        return choice == "on", "contact"
    for name in categories:
        if rules.tags.get(name) == "on":
            return True, f"tag:{name}"
    for name in categories:
        if rules.tags.get(name) == "off":
            return False, f"tag:{name}"
    return rules.everything, "everything"


def set_choice(settings: Settings, uid: str, state: str) -> None:
    """state: 'on', 'off', or 'follow' (back to the tag rules)."""
    with db.session(settings.db_path) as conn:
        if state == "follow":
            conn.execute("DELETE FROM phone_choice WHERE uid = ?", (uid,))
        else:
            conn.execute(
                "INSERT INTO phone_choice (uid, state) VALUES (?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET state = excluded.state",
                (uid, state),
            )


def set_rule(settings: Settings, name: str, state: str) -> None:
    """name: a tag or deck, or EVERYTHING. state: 'on', 'off', or 'follow' to clear it."""
    with db.session(settings.db_path) as conn:
        if state == "follow" or (name == EVERYTHING and state == "off"):
            conn.execute("DELETE FROM phone_rules WHERE name = ?", (name,))
        else:
            conn.execute(
                "INSERT INTO phone_rules (name, state) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET state = excluded.state",
                (name, state),
            )
