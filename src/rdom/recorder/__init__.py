"""Gameplay recorder: frames + normalized pointer actions on one clock.

Platform-free modules (``geometry``, ``events``, ``frames_index``, ``verify``,
``config``, ``session``) import anywhere and are unit-tested. The Windows-only
modules (``window``, ``capture``, ``encoder``, ``hook``, ``record``) are
imported lazily by the entry point so that tooling on other platforms can still
load the package.
"""
