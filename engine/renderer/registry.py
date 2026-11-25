"""The renderer registry: name -> factory.

``"Forward"`` -- Classic -- is Fio's built-in renderer, and the only one the
host draws with (:func:`renderer_from_settings`; while :data:`ENFORCE_CLASSIC`
holds, ``QtGameView`` refuses to switch to any other). Another renderer can
still be registered with :func:`register_renderer` and made with
:func:`create_renderer` -- the contract's tests and the example in
``docs/examples`` do -- but the host does not draw with it. A factory is any
callable ``factory(config)`` that returns an object satisfying
:class:`engine.renderer.api.Renderer` -- usually the renderer class itself. :func:`create_renderer` checks that it does,
whichever renderer it is: the built-in ones are held to the contract exactly
as a plugin's is.

Built-in entries are named by import path and resolved on first use, so
importing the registry (or the contract) needs no OpenGL.
"""

import importlib


class RendererContractError(TypeError):
    """A renderer factory's object does not satisfy the renderer contract
    (engine.renderer.api.contract_violations): a member is missing or cannot
    be read, a method does not take the contract's arguments, an attribute
    holds a value of the wrong type, or it does not declare a contract
    version this Fio can run."""


class RendererInitError(RuntimeError):
    """A renderer could not be started: importing its factory or calling it
    raised (a missing library, a bug in its constructor -- a TypeError there
    included). The original exception is its ``__cause__``. Not a verdict
    on the contract."""

#: The renderer the host draws with: Fio's original forward renderer, the
#: one people call Classic. It is the only renderer Fio ships, and the host
#: uses it whatever settings.ini, a map or the console ask for.
DEFAULT_RENDERER = "Forward"

#: What a person calls the default renderer.
CLASSIC = "Classic"

#: Other names a renderer answers to. "Classic" is what the forward renderer
#: has been called since there was a second one.
ALIASES = {CLASSIC: DEFAULT_RENDERER}

#: The host draws with Classic only: ``QtGameView.switch_renderer`` and the
#: console's ``r_renderer`` refuse every other name while this is true, a
#: renderer a plugin registers included. Nothing in Fio turns it off; the
#: tests of the host's own swap machinery do, to swap in their stand-in
#: renderers and back.
ENFORCE_CLASSIC = True


def classic_enforced():
    """Whether the host may draw with Classic only (:data:`ENFORCE_CLASSIC`,
    read when asked)."""
    return bool(ENFORCE_CLASSIC)

_factories = {
    DEFAULT_RENDERER: "engine.renderer.forward:ForwardRenderer",
}


def renderer_from_settings(config=None):
    """The registry name of the renderer the host draws with: always
    Classic (``"Forward"``).

    ``[Renderer] renderer`` in settings.ini is not consulted: an older file
    that names a renderer Fio no longer ships (such as ``HD_High``), any
    other value, or none at all, all start Classic."""
    return DEFAULT_RENDERER


def is_classic(name):
    """Whether *name* (a registry name or an alias, any case) is Classic."""
    text = str(name or "").strip().lower()
    return text in (DEFAULT_RENDERER.lower(), CLASSIC.lower())


def canonical_name(name):
    """The registry key *name* stands for (an alias resolved; anything else
    as given)."""
    return ALIASES.get(name, name)


def register_renderer(name, factory):
    """Register *factory* under *name*, replacing any previous entry. Returns True."""
    _factories[str(name)] = factory
    return True


def available_renderers():
    """The registered renderer names."""
    return list(_factories)


def renderer_factory(name):
    """The factory registered under *name*, or None."""
    name = canonical_name(name)
    factory = _factories.get(name)
    if isinstance(factory, str):
        module_name, _, attr = factory.partition(':')
        factory = getattr(importlib.import_module(module_name), attr)
        _factories[name] = factory
    return factory


def _retire(renderer):
    """Clean up a renderer the registry refused. Returns the exception its
    ``cleanup`` raised, or None."""
    try:
        renderer.cleanup()
    except Exception as exc:
        return exc
    return None


def create_renderer(name=DEFAULT_RENDERER, config=None):
    """Create the renderer registered under *name* (GL context current).

    What the factory returns is checked against the contract before the host
    paints with it (:func:`~engine.renderer.api.contract_violations`): every
    member of :class:`~engine.renderer.api.Renderer` is there and can be
    read, each method takes the arguments the contract declares, each
    attribute holds a value of its declared type, and it declares a
    ``contract_version`` this Fio can run. One refused is cleaned up first,
    so the GL objects it made do not outlive it.

    Raises KeyError for an unknown name; :class:`RendererInitError` when the
    factory cannot be imported or raises; :class:`RendererContractError` for
    an object that does not satisfy the contract, naming every violation.
    """
    from .api import contract_violations
    name = canonical_name(name)
    if name not in _factories:
        raise KeyError(f"no renderer registered as {name!r}")
    try:
        factory = renderer_factory(name)
        renderer = factory(config)
    except Exception as exc:
        raise RendererInitError(
            f"renderer {name!r} failed to start: {type(exc).__name__}: {exc}") from exc
    violations = contract_violations(renderer)
    if violations:
        error = RendererContractError(
            f"renderer {name!r} does not satisfy the renderer contract: "
            + "; ".join(violations))
        failed = _retire(renderer)
        if failed is not None:
            error.add_note(
                f"its cleanup() raised {type(failed).__name__}: {failed}; "
                "GL objects it made may remain")
        raise error
    return renderer
