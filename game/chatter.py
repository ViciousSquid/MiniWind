"""
What townsfolk say to each other: rumours passed on aloud and passing small
talk, as two-line exchanges the HUD shows over their heads.

Pure Python. The rumours themselves are the reactive simulation's
(:func:`game.sim.knowledge.gossip`); this module only puts words to an exchange
that has already happened, so what is said is always what was actually passed
on. Lines are picked by a stable hash of who is talking and about what, so the
same pair telling the same story says it the same way.
"""

from __future__ import annotations

import zlib
from typing import Dict, Tuple

#: How a rumour is opened, by how the speaker came to know it.
_OPENERS = {
    "witnessed": ("I saw it with my own eyes: {what}.", "You won't believe what I saw. {What}.",
                  "I was there! {What}."),
    "heard": ("I heard it happen: {what}.", "There was such a commotion. {What}."),
    "told": ("Did you hear? {What}.", "They're saying {what}.", "Word is, {what}."),
}

#: The listener's reply, by what sort of news it is (the event kind's tags).
_REPLIES = {
    "grave": ("Gods preserve us.", "Dead? I'll bar my door tonight.",
              "Someone should fetch the watch."),
    "violence": ("In broad daylight? I'll keep my distance.", "The watch had better hear of this."),
    "property": ("I'll keep a hand on my purse.", "Thieves, here? Lock everything."),
    "social": ("Kind of them.", "Well, that's good to hear for once."),
    "": ("Is that so?", "Huh. Who'd have thought.", "You don't say."),
}

#: Passing small talk, by time of day: (opener, reply) pairs.
_SMALL_TALK = {
    "morning": (("Morning, {b}.", "Morning, {a}. Up early again?"),
                ("Another day, eh {b}?", "Another day, another coin."),
                ("Sleep well, {b}?", "Like a log, thank you.")),
    "day": (("Busy day, {b}?", "Never-ending, {a}. Never-ending."),
            ("Fine weather, isn't it?", "Won't last. It never does."),
            ("How's the family, {b}?", "Can't complain, {a}. Can't complain.")),
    "evening": (("Long day, {b}?", "Too long. I'm off home."),
                ("Evening, {b}.", "Evening, {a}. Mind how you go."),
                ("Heading to the tavern?", "Not tonight, {a}. I'm done in.")),
    "night": (("Still up, {b}?", "Can't sleep. You?"),
              ("Quiet night.", "Let's hope it stays that way.")),
}


def _pick(options, *salt):
    return options[zlib.crc32("|".join(str(s) for s in salt).encode()) % len(options)]


def _part_of_day(hour: float) -> str:
    hour = float(hour) % 24.0
    if 5.0 <= hour < 11.0:
        return "morning"
    if 11.0 <= hour < 17.0:
        return "day"
    if 17.0 <= hour < 22.0:
        return "evening"
    return "night"


def gossip_lines(fact: Dict, speaker: str = "", listener: str = "") -> Tuple[str, str]:
    """``(opener, reply)`` for *speaker* telling *listener* about *fact*."""
    from .sim import events, knowledge
    what = knowledge.phrase(fact)
    source = str(fact.get("source", "told"))
    salt = (speaker, listener, fact.get("e", 0))
    opener = _pick(_OPENERS.get(source, _OPENERS["told"]), *salt).format(
        what=what, What=what[:1].upper() + what[1:])
    tags = events.kind_spec(fact.get("kind", ""))["tags"]
    kind = next((t for t in ("grave", "violence", "property", "social") if t in tags), "")
    return opener, _pick(_REPLIES[kind], *salt)


def small_talk(a: str, b: str, hour: float) -> Tuple[str, str]:
    """``(opener, reply)`` for *a* passing the time of day with *b*."""
    part = _part_of_day(hour)
    opener, reply = _pick(_SMALL_TALK[part], a, b, part, int(hour))
    return opener.format(a=a, b=b), reply.format(a=a, b=b)
