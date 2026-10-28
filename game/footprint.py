"""The player's footprint is a projection, never a second reputation ledger."""

from .sim import crime


def market_traffic(board):
    traffic = {}
    if board is not None:
        for j in board.journeys.values():
            if j.kind in ("market", "trader", "caravan") and j.state != "done" and j.alive():
                for town in set((j.origin, j.dest)):
                    traffic[town] = traffic.get(town, 0) + 1
    return traffic


def town_prosperity(board, town):
    return min(1.0, market_traffic(board).get(town, 0) / 4)


def evaluate(accounts=(), *, threads=0, writs=None, vendettas=0, traffic=None, wealth=0, karma=0):
    """Inspectable state in, detached sensors out; no history oracle or RNG.

    The existing Karma remains the moral axis. Legend records which good and
    evil deeds people actually know; Karma alone supplies no testimony.
    """
    from .rpg import alignment
    known = {}
    for holder, facts in accounts:
        for f in facts:
            if (f.get("actor") != "player" or not f.get("identified", True)
                    or float(f.get("certainty", 0)) < crime.REPORT_CERTAINTY or not f.get("e")):
                continue
            prior = known.get(f["e"])
            if prior is None or f["certainty"] > prior[1]["certainty"]:
                known[f["e"]] = (holder, f)
    good = sum(f["certainty"] for _, f in known.values() if f.get("kind") in ("heal", "gift"))
    evil = sum(f["certainty"] for _, f in known.values() if crime.is_crime(f))
    debt = sum(max(0, row.get("bounty", 0)) for row in (writs or {}).values())
    traffic = dict(traffic or {})
    return dict(prosperity=min(1.0, max(0, wealth) / 2000 + sum(traffic.values()) / 20),
                notoriety=min(1.0, threads / 8 + vendettas / 4 + debt / 1000),
                legend=round(good - evil, 6), good=round(good, 6), evil=round(evil, 6),
                karma=float(karma), karma_tier=alignment.tier(karma), traffic=traffic,
                receipts=[dict(event=e, holder=h, kind=f.get("kind"))
                          for e, (h, f) in sorted(known.items())])
