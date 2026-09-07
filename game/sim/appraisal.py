"""
Interpretation — the same fact means different things to different people.

This is the step between *knowing* and *doing*, and it is where the characters
actually live. One murder produces, from one shared fact:

* the victim's brother → **FIGHT** ("you killed my sister")
* the baker who saw it → **REPORT** ("I must tell the watch")
* a guard who saw it   → **ARREST** ("you are wanted for murder")
* a coward who saw it  → **FLEE** ("I want no part of this")
* the victim's rival   → **IGNORE** ("no loss")

None of those are branches on a scenario. They are the same function reading
different observers: their relationships, faction, courage, disposition toward
the offender, and whether the goods in question were theirs.

Every :class:`Intent` carries a ``reason`` in plain English. That string is what
the editor's **Live Simulation Inspector** shows when a designer asks "why is
she doing that?", so the explanation is produced by the decision itself and can
never drift out of step with it.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from . import crime as crime_mod
from . import ownership
from .events import kind_spec

# --- reactions -------------------------------------------------------------
FIGHT = "FIGHT"
FLEE = "FLEE"
ARREST = "ARREST"
REPORT = "REPORT"
CONFRONT = "CONFRONT"
MOURN = "MOURN"
WARM = "WARM"
IGNORE = "IGNORE"

#: Priority bands, deliberately sharing the scale used by
#: :mod:`game.mental_state` so a sim intent and a schedule task can be ranked
#: against one another in a single list.
PRIORITY = {
    FIGHT: 100,
    FLEE: 90,
    ARREST: 95,
    CONFRONT: 80,
    REPORT: 75,
    MOURN: 45,
    WARM: 15,
    IGNORE: 0,
}

#: Courage at or above this makes an actor stand rather than run when the
#: threat is personal. Below it they flee. Modified by how grave the deed was.
STAND_COURAGE = 0.5

#: Relationship labels that make somebody's death personal. Anything not listed
#: is still weighed through disposition, so an authored "rival" or "debtor"
#: works without being enumerated here.
KIN_TIES = ("sibling", "brother", "sister", "spouse", "wife", "husband",
            "parent", "mother", "father", "child", "son", "daughter")
WARM_TIES = KIN_TIES + ("friend", "courting", "lover", "ally", "partner")
COLD_TIES = ("rival", "enemy", "nemesis", "debtor", "creditor")


class Intent:
    """One ranked thing an actor wants to do, and why."""

    __slots__ = ("reaction", "priority", "target", "target_name", "reason",
                 "fact", "event_id")

    def __init__(self, reaction: str, target: str = "", target_name: str = "",
                 reason: str = "", fact: Optional[Dict] = None,
                 priority: Optional[int] = None):
        self.reaction = reaction
        self.priority = int(PRIORITY.get(reaction, 0) if priority is None else priority)
        self.target = str(target or "")
        self.target_name = str(target_name or target or "")
        self.reason = str(reason)
        self.fact = fact
        self.event_id = int((fact or {}).get("e", 0) or 0)

    @property
    def label(self) -> str:
        verb = {
            FIGHT: "Attack", FLEE: "Flee from", ARREST: "Arrest",
            CONFRONT: "Confront", REPORT: "Report", MOURN: "Mourn",
            WARM: "Warm to", IGNORE: "Ignore",
        }.get(self.reaction, self.reaction.title())
        return f"{verb} {self.target_name}".strip() if self.target_name else verb

    def to_dict(self) -> Dict:
        return {"reaction": self.reaction, "priority": self.priority,
                "target": self.target, "target_name": self.target_name,
                "reason": self.reason, "event": self.event_id}

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Intent {self.reaction} p{self.priority} {self.target_name!r}>"


# ---------------------------------------------------------------------------
# Context — everything appraisal needs from the wider game, as plain callables
# ---------------------------------------------------------------------------
class Context:
    """The world knowledge appraisal borrows, injected rather than imported.

    Keeping these as callables is what lets the whole interpretation step be
    unit-tested with three lambdas and no engine at all."""

    def __init__(self, hostile: Optional[Callable[[str, str], bool]] = None,
                 disposition: Optional[Callable[[Dict, str], int]] = None,
                 self_key: str = "", store=None):
        #: ``hostile(faction_a, faction_b) -> bool``
        self.hostile = hostile or (lambda a, b: False)
        #: ``disposition(observer_props, other_key) -> 0-100``
        self.disposition = disposition or (lambda props, key: 50)
        self.store = store


def relationship_to(observer_props: Dict, key: str, name: str = "") -> str:
    """The authored tie from this observer to another actor, or ``""``.

    Relationships are authored as ``{name: "sister"}`` on the NPC, so both the
    stable key and the display name are checked."""
    rels = observer_props.get("relationships")
    if not isinstance(rels, dict):
        return ""
    for candidate in (name, key):
        if not candidate:
            continue
        for k, v in rels.items():
            if str(k).lower() == str(candidate).lower():
                return str(v).lower()
    return ""


def _courage(props: Dict) -> float:
    try:
        return max(0.0, min(1.0, float(props.get("courage", 0.3))))
    except (TypeError, ValueError):
        return 0.3


def is_combatant(props: Dict) -> bool:
    """Whether an actor can and will fight — a capability deliberately separate
    from its faction and from the civilian flee reaction.

    This is the single definition MiniWind uses: ``MiniwindSession._is_combatant``
    delegates here rather than keeping its own copy."""
    if not isinstance(props, dict):
        return False
    if "combatant" in props:
        return bool(props.get("combatant"))
    return (str(props.get("aggression")) in ("defensive", "hostile")
            or bool(props.get("can_defend"))
            or str(props.get("npc_role", "")).lower().startswith("guard"))


def _faction(props: Dict) -> str:
    return str(props.get("faction") or props.get("team") or "").lower()


# ---------------------------------------------------------------------------
# The interpretation itself
# ---------------------------------------------------------------------------
def appraise(observer_props: Dict, observer_key: str, fact: Dict,
             ctx: Optional[Context] = None) -> Optional[Intent]:
    """Turn one believed fact into at most one ranked :class:`Intent`.

    Returns ``None`` when the observer simply does not care — which is most of
    the time, and is what keeps a settlement from erupting over every event."""
    if not isinstance(fact, dict) or not isinstance(observer_props, dict):
        return None
    if observer_props.get("dead"):
        return None
    ctx = ctx or Context()

    kind = str(fact.get("kind", ""))
    tags = kind_spec(kind)["tags"]
    offender = str(fact.get("actor", ""))
    offender_name = str(fact.get("actor_name", "") or offender)
    victim = str(fact.get("target", ""))
    victim_name = str(fact.get("target_name", "") or victim)
    certainty = float(fact.get("certainty", 0.0))

    if offender and offender == observer_key:
        return None                      # nobody reacts to their own deeds
    if certainty < 0.15:
        return None                      # too vague to act on

    is_offence = crime_mod.is_crime(fact)
    victim_is_self = bool(victim) and victim == observer_key
    tie = relationship_to(observer_props, victim, victim_name)
    stance = ctx.disposition(observer_props, offender)
    courage = _courage(observer_props)
    combatant = is_combatant(observer_props)
    lawful = crime_mod.is_lawful(observer_props)
    hostile_faction = ctx.hostile(_faction(observer_props),
                                  str(fact.get("actor_faction", "")))

    # -- 1. it happened to me -------------------------------------------
    if victim_is_self and "violence" in tags:
        if combatant or courage >= STAND_COURAGE:
            return Intent(FIGHT, offender, offender_name,
                          f"{offender_name} attacked me and I will not run "
                          f"(courage {courage:.2f})", fact)
        return Intent(FLEE, offender, offender_name,
                      f"{offender_name} attacked me and I am no fighter "
                      f"(courage {courage:.2f})", fact)

    if victim_is_self and "property" in tags and kind == "theft":
        return Intent(CONFRONT, offender, offender_name,
                      f"{offender_name} took what is mine", fact)

    # -- 2. it happened to someone I care about --------------------------
    if "grave" in tags and tie:
        if tie in COLD_TIES:
            return Intent(IGNORE, offender, offender_name,
                          f"{victim_name} was my {tie}; no loss to me", fact)
        if tie in WARM_TIES:
            grief_courage = courage + 0.25   # grief lends nerve
            if combatant or grief_courage >= STAND_COURAGE:
                return Intent(FIGHT, offender, offender_name,
                              f"{offender_name} killed {victim_name}, my {tie}",
                              fact)
            return Intent(MOURN, offender, offender_name,
                          f"{victim_name}, my {tie}, is dead and I cannot avenge "
                          f"them", fact)

    # -- 3. it is a crime and I am the law -------------------------------
    if is_offence and lawful and certainty >= crime_mod.REPORT_CERTAINTY:
        grave = "grave" in tags
        return Intent(ARREST, offender, offender_name,
                      f"I {'saw' if fact.get('source') == 'witnessed' else 'know'} "
                      f"{offender_name} commit {'murder' if grave else kind}; "
                      f"that is my duty", fact)

    # -- 4. it is a crime and I am not the law ---------------------------
    if is_offence and not fact.get("reported"):
        if courage < 0.2 and "violence" in tags:
            return Intent(FLEE, offender, offender_name,
                          f"{offender_name} is violent and I want no part of it",
                          fact)
        return Intent(REPORT, offender, offender_name,
                      f"Somebody must tell the watch what {offender_name} did",
                      fact)

    # -- 5. a threat in the world, not aimed at me -----------------------
    if "violence" in tags and hostile_faction:
        if combatant and courage >= STAND_COURAGE:
            return Intent(FIGHT, offender, offender_name,
                          f"{offender_name} is an enemy of my people", fact)
        return Intent(FLEE, offender, offender_name,
                      f"There is fighting nearby and I am not part of it", fact)

    # -- 6. somebody did something kind ----------------------------------
    if "social" in tags and kind in ("gift", "heal"):
        if victim_is_self or tie in WARM_TIES:
            who = "me" if victim_is_self else f"{victim_name}, my {tie}"
            return Intent(WARM, offender, offender_name,
                          f"{offender_name} was good to {who}", fact)

    # -- 7. grave news about a stranger ----------------------------------
    if "grave" in tags and stance is not None and stance < 25:
        return Intent(IGNORE, offender, offender_name,
                      f"{offender_name} is dangerous; I keep my distance", fact)

    return None


def appraise_all(observer_props: Dict, observer_key: str, facts: List[Dict],
                 ctx: Optional[Context] = None) -> List[Intent]:
    """Appraise every fact and return the intents, most urgent first.

    At most one intent per offender survives, so knowing four things about the
    same person produces one considered response rather than four."""
    best: Dict[str, Intent] = {}
    for f in facts or ():
        intent = appraise(observer_props, observer_key, f, ctx)
        if intent is None:
            continue
        prior = best.get(intent.target)
        if prior is None or intent.priority > prior.priority:
            best[intent.target] = intent
    out = list(best.values())
    out.sort(key=lambda i: -i.priority)
    return out


def explain(intents: List[Intent]) -> str:
    """The one-line 'why is this actor doing that?' string for the inspector."""
    if not intents:
        return "Nothing it knows about demands a response — following its schedule."
    top = intents[0]
    return f"{top.label} — {top.reason}"
