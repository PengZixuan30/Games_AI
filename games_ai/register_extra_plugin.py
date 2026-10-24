"""Hot-reload registration under its pre-0.8.0 import path.

``register_self`` and the registry it writes into moved to
:mod:`games_ai.ai.register_extra_plugin` when the package grew its subpackages, but
``games_ai.register_extra_plugin`` is the path the released Hot reload guide has always told
another plugin's ``on_load`` to import. This module keeps that path working by re-exporting the
real module's public names -- the very same function and the same registry, so a plugin that
registers itself through either path is reloaded by the one list the plugin reads -- and nothing
else: no module of the plugin imports it (it exists for code outside), and new code belongs on the
real path (see ``docs/*/hot-reload.md``).

``tests/test_compat_modules.py`` pins the contract: this module exposes exactly the public surface
of :mod:`games_ai.ai.register_extra_plugin`, the same objects, so an old plugin needs no edit.
"""

from .ai.register_extra_plugin import REGISTER_PLUGIN_LIST, register_self
