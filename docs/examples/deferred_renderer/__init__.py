"""An example plugin that adds a deferred renderer to Fio.

It shows how a renderer is written against the public contract and
registered. Fio itself draws with Classic only
(``engine.renderer.registry.ENFORCE_CLASSIC``): copied into ``plugins/`` it is
registered, but the host does not switch to it. Its tests swap it in with
that enforcement lifted (``tests/e2e/test_deferred_renderer_example.py``).
See the wiki's Renderer Development Guide for a walk through the code.
"""

from plugins.api import FioPlugin


def _create_deferred_renderer(config):
    # Imported when the host creates the renderer -- with its GL context
    # current -- so loading the plugin needs no OpenGL.
    from .renderer import DeferredRenderer
    return DeferredRenderer(config)


class DeferredRendererPlugin(FioPlugin):
    name = "deferred_renderer"
    version = "1.0.0"
    description = "Example: a deferred renderer (r_renderer Deferred)"
    api_version = "2.0.0"          # the current Renderer contract requires 1.9.0

    def register(self, api):
        api.register_renderer("Deferred", _create_deferred_renderer)


PLUGIN = DeferredRendererPlugin()
