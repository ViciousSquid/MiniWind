"""
MiniWind's **reactive simulation layer** — author causality, not stories.

Nothing in this package knows about any particular scenario. It provides the
small, composable mechanisms whose *interactions* produce the stories:

``events``       a world event bus — every notable thing that happens, as data
``perception``   who could have seen or heard an event (witnesses)
``knowledge``    what each actor believes, how sure they are, and where it came
                 from (witnessed / heard / told) — plus rumour propagation
``ownership``    who owns a thing; what counts as theft
``crime``        a crime table, reporting, and bounty as a *consequence* of
                 someone knowing and telling, not of the act itself
``appraisal``    how one actor interprets one thing it knows — and *why*
``production``   objects that make other objects over time (a cow → milk)
``director``     the glue: EVENT → PERCEPTION → INTERPRETATION → STATE CHANGE →
                 BEHAVIOUR, plus the explanation trail the editor inspects

The pipeline is deliberately one-directional and general-purpose::

    session emits a WorldEvent
        → perception picks the witnesses (sight / sound / asleep / distance)
            → knowledge stores a Fact per witness (certainty, source)
                → appraisal turns each Fact into a ranked Intent + a reason
                    → the runtime's decision tick honours the top Intent

No step knows what event it is handling, so a new event kind, a new actor or a
new object gains the whole chain for free. Every module here is pure Python:
no Qt, no OpenGL, no engine imports — so all of it is headlessly testable.
"""

from .events import WorldEvent, EventBus, EVENT_KINDS  # noqa: F401
from .director import Director, Intent  # noqa: F401
