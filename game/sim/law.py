"""Local writs and the hue and cry. Knowledge still decides who tells the law.

This ledger records consequences *after* testimony reaches a watchman. It never
notifies distant guards, creates witnesses, or erases anyone's personal memory.
All time is in world hours; all positions use the world's X/Z ground plane.
"""

from __future__ import annotations

import json
import math

SEARCH_RADIUS = 1000.0
SEARCH_HOURS = 0.25
BLOOD_SEARCH_HOURS = 0.75
CURFEW_HOURS = 6.0
KEY = "law.writs"


def distance(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


class Writs:
    """Persistent per-jurisdiction debts, searches, and temporary curfews."""

    def __init__(self, store):
        self.store = store
        self.regions = {}
        self.restore()

    def restore(self):
        try:
            data = json.loads(self.store.get(KEY, "{}"))
        except (TypeError, ValueError):
            data = {}
        self.regions = data if isinstance(data, dict) else {}

    def persist(self):
        self.store.set(KEY, json.dumps(self.regions))

    def record(self, region):
        return self.regions.setdefault(str(region), {
            "charges": {}, "phase": "clear", "last_pos": None,
            "unseen": 0.0, "stamp": None, "curfew_until": 0.0,
            "grave_times": [], "bell_at": -1e9})

    def bounty(self, region):
        return sum(int(c["amount"]) for c in self.record(region)["charges"].values())

    @property
    def total(self):
        return sum(self.bounty(r) for r in list(self.regions))

    def blood_writ(self, region):
        return any(c.get("grave") for c in self.record(region)["charges"].values())

    def charge(self, region, event_id, amount, now, *, grave=False):
        row = self.record(region)
        key = str(event_id)
        if key in row["charges"] or amount <= 0:
            return False
        row["charges"][key] = {"amount": int(amount), "grave": bool(grave)}
        if row["phase"] == "clear":
            row["phase"] = "writ"
        if grave:
            row["grave_times"] = [t for t in row["grave_times"] if now - t <= 1.0]
            row["grave_times"].append(now)
            if len(row["grave_times"]) >= 3:
                row["curfew_until"] = now + CURFEW_HOURS
        self.persist()
        return True

    def migrate(self, region, legacy_bounty):
        """Old saves have one purse; preserve it as a writ in their home region."""
        if not self.total and legacy_bounty > 0:
            self.charge(region, "legacy", legacy_bounty, 0.0,
                        grave=legacy_bounty >= 1000)

    def forgive(self, region, fraction):
        """Let *fraction* of the region's lesser charges go (a watchman talked
        round). A blood writ is never forgiven. Returns the gold forgiven."""
        row = self.record(region)
        forgiven = 0
        for key, c in list(row["charges"].items()):
            if c.get("grave"):
                continue
            cut = int(round(int(c["amount"]) * float(fraction)))
            c["amount"] = int(c["amount"]) - cut
            forgiven += cut
            if c["amount"] <= 0:
                del row["charges"][key]
                self.store.set(f"crime.{key}.settled", "1")
        if not row["charges"]:
            row["phase"] = "clear"
        self.persist()
        return forgiven

    def settle(self, region):
        row = self.record(region)
        amount = self.bounty(region)
        for eid in row["charges"]:
            self.store.set(f"crime.{eid}.settled", "1")
        row["charges"] = {}
        row["phase"] = "clear"
        row["last_pos"] = None
        row["unseen"] = 0.0
        # The watch lifts its pursuit; the town still observes its curfew.
        self.persist()
        return amount

    def curfew(self, region, now):
        return now < self.record(region)["curfew_until"]

    def sighted(self, region, pos, now):
        row = self.record(region)
        row.update(phase="pursuit", last_pos=list(pos), unseen=0.0, stamp=now)

    def abandon_search(self, region):
        row = self.record(region)
        row.update(phase="writ" if self.bounty(region) else "clear", unseen=0.0)

    def search(self, region, pos, now):
        """Freeze the last sighting; drain heat only while outside its circle."""
        row = self.record(region)
        prior = row["stamp"]
        elapsed = max(0.0, now - prior) if prior is not None else 0.0
        row["stamp"] = now
        if row["last_pos"] is None:
            self.abandon_search(region)
            return True
        row["phase"] = "search"
        if distance(pos, row["last_pos"]) > SEARCH_RADIUS:
            row["unseen"] += elapsed
        else:
            row["unseen"] = 0.0
        duration = BLOOD_SEARCH_HOURS if self.blood_writ(region) else SEARCH_HOURS
        if row["unseen"] >= duration:
            self.abandon_search(region)
            return True
        return False

    def remaining(self, region):
        duration = BLOOD_SEARCH_HOURS if self.blood_writ(region) else SEARCH_HOURS
        return max(0.0, 1.0 - self.record(region)["unseen"] / duration)
