"""A plugin that owns two entity types and extends a core one.

The shape of Fio's Tidy plugin, which MiniWind does not ship: its own
``extenderbin`` and ``extendergoal`` types with I/O of their own, and an
input and an output added to the core ``prop`` type with ``extend_io``. The
registration-replay tests use it to check that both kinds of registration
are recorded and restored.
"""

from plugins.api import FioPlugin, io_def
from plugins.entitybase import Thing


class ExtenderBin(Thing):
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault("type", "extenderbin")


class ExtenderGoal(Thing):
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault("type", "extendergoal")


class PropExtenderPlugin(FioPlugin):
    name = "prop_extender"
    version = "1.0.0"
    api_version = "1.5.0"
    description = "Owns two entity types and adds I/O to the core prop."
    category = "Tests"
    enabled = True

    def register(self, api):
        api.register_entity(ExtenderBin, menu_label="Extender Bin")
        api.register_entity(ExtenderGoal, menu_label="Extender Goal")
        api.register_io("extenderbin",
                        inputs=[io_def("Empty", "Empty the bin")],
                        outputs=[io_def("OnFilled", "A prop was put in")])
        api.register_io("extendergoal",
                        inputs=[io_def("Check", "Check the goal")],
                        outputs=[io_def("OnMet", "Every bin is filled")])
        api.extend_io("prop",
                      inputs=[io_def("Restock", "Put the prop back where it started")],
                      outputs=[io_def("OnRestocked", "The prop went back")])


PLUGIN = PropExtenderPlugin()
