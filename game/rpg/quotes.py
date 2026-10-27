"""
The words that greet a level-up: a line of encouragement from an unseen
Dungeon Master leaning over the screen -- written for players who know
their saving throws from their hit dice, set in the Vale's sword-and-sorcery
world.

All original to Miniwind. One is picked per level, so the same level always
reads the same and two levels in a row never repeat. ``[GAME]
motivational_quotes = False`` in ``settings.ini`` turns them off (it is not
offered in the in-game settings).
"""

from __future__ import annotations

QUOTES = (
    "The Dungeon Master glances at your sheet, then at you, and slowly "
    "slides the encounter notes back behind the screen. They will need "
    "bigger monsters.",
    "You wake with the feeling that somewhere, unseen, a die has been "
    "rolled in your favour. Do not ask who rolled it. Do not ask what it "
    "was for.",
    "Last level you would have needed a natural twenty for that. Now a "
    "twelve will do. Remember this feeling when the dragon rolls initiative.",
    "The voice behind the screen clears its throat: \"You may add your new "
    "bonus. Yes, to everything. No, you may not have done that last week.\"",
    "Every failed save you have made is written in pencil in the margins of "
    "your sheet. Today you erase a few of them.",
    "Somewhere in the Vale, a random encounter table has quietly been "
    "re-rolled on your behalf. The wolves are not going to enjoy the update.",
    "You are no longer the hireling at the back holding the torch. The "
    "party would like to know when you started walking in front.",
    "The tavern bard has started a song about you. It is badly rhymed and "
    "mostly inaccurate. Your legend has officially begun.",
    "You hear dice clatter far away, then silence, then a single muttered "
    "\"...huh.\" Whatever just happened, you survived it with hit points to "
    "spare.",
    "The goblins have held a meeting. Your name came up. The vote to avoid "
    "you was unanimous.",
    "You roll to resist despair. The result is irrelevant: you were never "
    "going to despair. The Dungeon Master sighs and crosses out a page.",
    "Your character sheet is getting crowded. This is the good kind of "
    "problem; the other kind involves an eraser and a funeral.",
    "The prophecy did not mention you. Prophecies are written by people who "
    "had not yet met you.",
    "Advantage is a state of mind. Also, as of this level, a fair few "
    "actual numbers on your sheet.",
    "A voice from beyond the screen: \"Take a short rest. Have a snack. You've "
    "earned it. ...Something will be waiting for you when you're done.\"",
    "You have stopped counting the rats in the cellar and started counting "
    "the cellars. That, adventurer, is called a campaign.",
    "The innkeeper no longer asks you to pay in advance. In the Vale, there "
    "is no higher honour.",
    "Your hit dice grow. Your fears shrink. Your inventory, alas, still "
    "contains seventeen rusty spoons you refuse to sell.",
    "Somewhere a lich turns a page in its planning ledger, pauses at your "
    "name, and adds a footnote.",
    "The first time, you rolled a one and fell off the bridge. You remember. "
    "The bridge remembers. Neither of you will speak of it.",
    "Fortune favours the bold, but it keeps exact records. Today it settled "
    "an old account in your favour.",
    "Even the Dungeon Master did not expect you to get this far. Do not tell "
    "anyone. Act as if this was always the plan.",
    "A quest-giver in a distant village has just been written into "
    "existence, purely so they can beg for your help.",
    "Your mentor would be proud. Your mentor is dead -- roll for grief, then "
    "roll for revenge, then get on with the adventure.",
    "The difficulty class of the world has not changed. You have. That is "
    "the whole secret, and now you know it.",
    "You can almost feel the shape of the dice in the air around you. They "
    "are heavier on your side now.",
    "Traps you once triggered by accident you now spot by instinct. The "
    "dungeon builders of the Vale are drafting angry letters.",
    "The rules say you may not reroll your past. They say nothing about "
    "making the next roll count.",
    "The party's wizard muttered that you are \"actually quite competent\". "
    "They will deny saying it. You have a witness.",
    "Behind the screen, a stat block is being quietly rewritten. Somewhere "
    "a monster has just gained a few extra hit points, out of respect.",
    "You stand where a lesser hero would have rolled for a new character. "
    "Keep standing.",
    "A critical failure is only a story you have not finished telling. You "
    "have finished several. They end well.",
    "The map has more fog than it has land. The Dungeon Master leans in: "
    "\"So... where do you want to go next?\"",
    "Your saving throws improve. Your enemies' do not. Arithmetic, too, is "
    "a kind of sword.",
    "There is a dragon in this world that has never heard of you. Change "
    "that.",
    "The session is not over. The session is never over. Roll on.",
)


def for_level(level: int) -> str:
    """The quote for reaching *level*: fixed per level, and never the same
    as the one before it."""
    return QUOTES[(int(level) * 7) % len(QUOTES)]
