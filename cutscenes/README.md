# MiniWind Cutscenes

Cutscenes are standalone JSON assets.

The map only stores a `miniwindcutscene` trigger containing a `cutscene_file` reference. The JSON owns the timeline: actors, camera keyframes, movement, fights, dialogue, messages and blood/effect keyframes.

Use **Tools → Cutscene Wizard** to author them.

Cutscene files are ordinary JSON so they can be diffed, copied between maps and edited without opening the editor.
