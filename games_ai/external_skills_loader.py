"""Skill injection under its pre-0.8.0 import path.

``register_skills``, ``read_external_skills`` and the list they share moved to
:mod:`games_ai.ai.external_skills_loader` when the package grew its subpackages, but
``games_ai.external_skills_loader`` is the path the released Skills guide has always told another
plugin's ``on_load`` to import. This module keeps that path working by re-exporting the real
module's public names -- the very same list, so a skill injected through either path is served by
the one lookup the AI reads -- and nothing else: no module of the plugin imports it (it exists for
code outside), and new code belongs on the real path (see ``docs/*/skills.md``).

``tests/test_compat_modules.py`` pins the contract: this module exposes exactly the public surface
of :mod:`games_ai.ai.external_skills_loader`, the same objects, so an old plugin needs no edit.
"""

from .ai.external_skills_loader import EXTERNAL_SKILLS_LIST, read_external_skills, register_skills
