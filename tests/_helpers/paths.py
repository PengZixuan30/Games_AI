"""Where this checkout keeps the plugin, the docs and the tests.

Every suite used to carry one absolute Windows path to the developer's own checkout, which made
the whole suite unrunnable anywhere else and had to be edited by hand whenever the folder moved.
The paths are derived from this file instead: ``tests/_helpers/`` sits two levels under the
repository root, so ``TESTS_DIR`` is one level up and the repository is two more.
"""
import os

HELPERS_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(HELPERS_DIR)
REPO_ROOT = os.path.dirname(TESTS_DIR)
PKG = os.path.join(REPO_ROOT, "games_ai")
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
LANG_DIR = os.path.join(REPO_ROOT, "lang")
MANIFEST = os.path.join(REPO_ROOT, "mcdreforged.plugin.json")
JS_DIR = os.path.join(TESTS_DIR, "js")
