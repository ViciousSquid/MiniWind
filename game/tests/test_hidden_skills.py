"""A skill no rule reads is hidden until one does: Acrobatics ("jumping and
cushioning falls" -- MiniWind has neither). It stays in the character's
block for saves, races and classes, but the sheet, the creator and the
trainers leave it out.

Run:  python -m pytest game/tests/test_hidden_skills.py -q
"""

from __future__ import annotations

from ..rpg import classes, skills as sk, training
from ..rpg.character import Character


def test_acrobatics_is_the_one_hidden_skill():
    assert sk.HIDDEN == {sk.ACROBATICS}
    listed = [s for spec in sk.BY_SPEC.values() for s in spec]
    assert sk.ACROBATICS not in listed
    assert sorted(listed) == sorted(s for s in sk.SKILL_IDS if s != sk.ACROBATICS)
    # Still in every character's block, so saves and races keep working.
    c = Character.create("A", "tehani", "thief")
    assert sk.ACROBATICS in c.skills
    assert Character.from_dict(c.to_dict()).skills[sk.ACROBATICS] == c.skills[sk.ACROBATICS]


def test_no_trainer_teaches_a_hidden_skill():
    t = training.trainer_of({"trainer": {"skills": ["athletics", "acrobatics"],
                                          "rank": "Journeyman"}})
    assert t == {"skills": [sk.ATHLETICS], "rank": 50}
    assert training.trainer_of({"trainer": {"skills": ["acrobatics"]}}) is None


def test_a_custom_class_is_never_padded_with_a_hidden_skill():
    shown = [s for s in sk.SKILL_IDS if sk.is_shown(s)]
    klass = classes.make_custom("Odd", sk.STEALTH, [], shown[-3:])
    assert sk.ACROBATICS not in klass.major_skills and len(klass.major_skills) == 7


def test_the_creator_lists_no_hidden_major_skill(qt_app, monkeypatch):
    from PyQt5 import QtGui
    from ..ui import screens
    drawn = []
    monkeypatch.setattr(screens, "_cc_detail",
                        lambda painter, x, y, w, title, body: drawn.append(body))
    assert sk.ACROBATICS in classes.get("archer").major_skills

    class _S:
        open_screen = "charcreate"
    s = _S()
    st = screens._cc(s)
    st["step"] = screens._CC_STEPS.index("class")
    st["class"] = classes.CREATION_CLASS_IDS.index("archer")
    image = QtGui.QImage(1280, 720, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    try:
        screens._draw_charcreate(painter, s, image.width(), image.height())
    finally:
        painter.end()
    assert drawn and "Major skills:" in drawn[-1]
    assert "Acrobatics" not in drawn[-1] and "Marksman" in drawn[-1]
