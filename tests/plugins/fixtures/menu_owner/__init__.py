"""A plugin with its own Plugins-menu action and entity, that also ticks.

The part of Fio's Tidy plugin (which MiniWind does not ship) the Plugins menu
tests relied on: an entry of its own in the plugin's submenu ("Load Demo
map" in Tidy), an entity type it offers under Add entity, and a per-frame
tick.
"""

from plugins.api import FioPlugin
from plugins.entitybase import Thing


class MenuOwnerGoal(Thing):
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault("type", "menuownergoal")


class MenuOwnerPlugin(FioPlugin):
    name = "menu_owner"
    version = "1.0.0"
    description = "Adds a Plugins-menu action and ticks."
    category = "Tests"
    enabled = True

    def __init__(self):
        self.calls = []
        self.ticks = 0

    def register(self, api):
        api.register_entity(MenuOwnerGoal, menu_label="Menu Owner Goal")
        api.register_menu_action("Load Demo map", self.load_demo,
                                 tooltip="Open the plugin's demo map")

    def load_demo(self, *args):
        self.calls.append(("load_demo", args))

    def on_tick(self, logic, ctx):
        self.ticks += 1


PLUGIN = MenuOwnerPlugin()
