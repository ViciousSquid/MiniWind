"""Resident mood at a touchpoint. No clocks, needs, writes or random draws."""

from .events import kind_spec


def evaluate(props, facts, prosperity=0.0, goodwill=0.0):
    """Return a detached mental state from current beliefs and local conditions.

    Prosperity is a 0..1 projection of existing market traffic; goodwill is
    the resident faction's current opinion of the subject. Neither is a need
    meter. With no remembered threat there is no invented enemy or intent.
    """
    from ..rpg import alignment
    courage = max(0.0, min(1.0, float(props.get("courage", 0.3))))
    # Only a remembered, identified deed exposes a player's Karma snapshot.
    # alignment.of_npc writes defaults, so resolve it on a detached dictionary.
    known_player = [f for f in facts if f.get("actor") == "player"
                    and f.get("identified", True) and f.get("actor_alignment") is not None
                    and float(f.get("certainty", 0)) >= 0.55]
    moral = max(known_player, key=lambda f: f.get("e", 0), default={}).get("actor_alignment", 0)
    affinity = alignment.affinity(moral, alignment.of_npc(dict(props)))
    threats = sorted({int(f.get("e", 0)) for f in facts
                      if f.get("identified", True)
                      and float(f.get("certainty", 0)) >= 0.55
                      and "violence" in kind_spec(f.get("kind", ""))["tags"]})
    prosperity = max(0.0, min(1.0, float(prosperity)))
    state = "steady"
    if threats:
        courage = max(0.0, min(1.0, courage + (prosperity - 0.5) * 0.2
                                   + max(-0.15, min(0.15, -goodwill / 200))
                                   + alignment.heartens(moral) + affinity / 200))
        state = "defiant" if courage >= 0.5 else "afraid"
    elif goodwill >= 10 and prosperity >= 0.5:
        state = "hopeful"
    elif prosperity < 0.25 and goodwill <= -20:
        state = "restless"
    return dict(state=state, courage=courage, prosperity=prosperity,
                goodwill=float(goodwill), events=threats, known_karma=moral, affinity=affinity)
