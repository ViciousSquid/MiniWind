# Fio's example maps, for tests only

MiniWind does not ship Fio's example maps (its `maps/` folder is the game's
own world). These four, from Fio 3.5.0.1111 (`9b2dca95`), are kept here
because Fio's renderer, decal, damage-indicator and brush-semantics tests are
written against them. Nothing in the game loads them.

`Reel_To_Reel_Test.json` is from Fio 3.5.2.2411 (`580e7ae`): the rotating
models test map (`tests/persistence/test_reel_to_reel_map.py`); its models are
in Fio's bundled `assets/bundled_reel_to_reel.fiopak`.
