"""Read-only projections shared by the Studio and causal history inspector."""


def world_explanations(story):
    """(group, label, reason, known event IDs); never sample the simulation."""
    if story is None:
        return [("Pacing", "Unavailable", "No active storyteller.", [])]
    view = story.world_view()
    rows = [("Pacing", story.state, dict(story.inspector_rows()).get("Arrival feedback", "Awaiting a sample."), [])]
    for town in view["threads"]:
        evidence = town["evidence"]
        rows.append(("Unreported threads", f"{town['town']} · {town['count']} threads · weight {town['bias']:g}",
            "; ".join(f"{r.get('holder_name', r['holder'])} ({r['holder']}) remembers {r['kind']} #{r['event']}" for r in evidence),
            sorted({r["event"] for r in evidence})))
    for key, row in view["vendettas"].items():
        rows.append(("Vendettas", f"{row.get('holder', key)} ({key})", f"{row['reason']}. {row['staging']}", [row["event"]]))
    for row in view["receipts"]:
        rows.append(("Journey outcomes", f"{row['journey']} {row.get('party', row['kind'])} ({row['kind']}) → {row['destination']} · {row['outcome']}",
            f"Hour {row['time']:.2f}, {row['state']}: {row['reason']}", row["events"]))
    return rows
