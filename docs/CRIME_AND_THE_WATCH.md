# Crime & the Settlement Watch

*MiniWind player guide · one-page subsystem tutorial*

## A crime needs a story

Assaulting townsfolk or the watch, killing protected people, and taking owned
goods can bring a charge. Fighting ordinary hostile enemies is lawful; making
a peaceful person fight back does not make further attacks lawful.

**Looking inside containers is free; taking owned contents is theft.** A
container with **Owner = None** is free for all and creates no theft or bounty.
Unlocking alone is free too. See [Locks & Containers](LOCKS_AND_CONTAINERS.md)
for mouse-controlled tumblers, lockpicks and editor settings.

An act alone does not give every guard knowledge of it. **“Someone witnessed
your crime.”** appears immediately when somebody sees it. **“Someone heard the
disturbance.”** means someone noticed trouble without necessarily identifying
you. A sound alone cannot put a named bounty on your head.

Witnesses seek the **nearest living guard**, find a route around walls, and
must reach speaking distance to testify. They choose another guard if their
target dies, can wake a sleeping watchman, and seek a guardpost if no guard
remains. News also travels through ordinary conversations. A dead witness
cannot testify, but accounts already shared with others survive.

## Read the warning signs

Open the world map with **M**, or watch your minimap:

| Marker | What it means |
| --- | --- |
| **Eye** | A witness can identify you. |
| **?** | Someone holds an uncertain or anonymous account. |
| **Red marker with an arrow** | A witness is attempting to report. |

Markers follow living witnesses carrying unreported accusations. They clear
after reporting or death. Once testimony reaches the watch, a local **writ**
records your bounty. Several accounts of one crime produce one charge; further
crimes add charges. Assault costs **40 gold**, murder **1,000 gold**, and theft
**25 gold plus the value taken**. The character sheet shows your total debt;
the watch notice names the current jurisdiction and its local amount.

## Escape the hue and cry

A guard who knows your writ and recognises you may stop you. Refusing arrest,
breaking away from an escort, or attacking the watch can start a pursuit.

**Break sight, leave the search circle, and remain unseen.** Darkness, sneaking,
walls and invisibility can help. Once sight is lost, the watch searches around
your last known position. A faint red circle with a gold rim marks that area;
**“Searching”** slowly orbits outside it. Its centre stays at the last sighting.

Remain outside and unseen for **15 game minutes**, or **45 game minutes for a
blood writ**. Being seen again resets the search; remaining inside the circle
prevents it cooling down. The search ending leaves your bounty outstanding.
Crossing a jurisdiction boundary also ends that pursuit without cancelling debt.

## Answer to the watch

Walk up to a settlement guard and press **E**. Choose **Settle my writ** to pay
that jurisdiction's full bounty. There are **no post offices**. An empty purse
does not cancel a balance, and guards will not take payment during a chase.

When stopped, you can also yield if the settlement has a gaol. **Stay close to
the escort** until arrival; running away brings the watch after you. Serving
time advances the world clock and discharges the local writ. Payment and gaol
leave other jurisdictions' debts and personal grudges intact.

Murder brings a **blood writ** and a hue and cry that alerts nearby watchmen.
**Three reported killings within one game hour** impose **six game hours of
curfew**, during which merchants refuse trade. Paying does not instantly lift
an existing curfew. Writs, searches and curfews survive saving and loading.

## Console controls

The physical key **below Esc** opens and closes the console: **§** on an ISO
Mac, or **` / ~** on a US keyboard. Use **`searchradius 0`** to hide the circle
and orbiting label; **`searchradius 1`** shows them again. This saved preference
only changes the visual. Guards continue searching normally.
