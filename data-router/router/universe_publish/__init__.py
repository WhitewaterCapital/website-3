"""DATA-02 (continued): sample synthetic universe data, a venue trading
calendar with half-days, and the "publish a dated universe file weekly"
mechanism.

NAMING NOTE — read this before wondering why the package isn't called
``universe/``: this task was scoped to add a new subpackage at
``data-router/router/universe/``. By the time this pass ran, a *different*
concurrent pass had already landed ``data-router/router/universe.py`` (a
module, not a package) implementing the core of DATA-02 — ``TradingCalendar``
and ``UniverseBuilder`` — with its own passing test suite
(``tests/test_universe.py``, part of the 105 tests green at the start of this
pass).

Creating a package directory literally named ``universe/`` alongside the
existing ``universe.py`` module in the same parent package is not just a
style clash: in CPython, a package (``universe/__init__.py``) *shadows* a
same-named module (``universe.py``) on ``sys.path`` resolution. Verified
empirically before writing anything here — introducing ``router/universe/``
makes ``import router.universe`` resolve to the new package and silently
stop seeing ``router/universe.py`` at all, which would break every one of
the 8 existing tests in ``tests/test_universe.py`` that do
``from router.universe import TradingCalendar, UniverseBuilder``. That is
exactly the kind of "do not touch existing files" violation this pass was
told to avoid, just achieved by a directory name instead of an edit.

So: this pass reuses the existing ``router.universe`` module as-is (imported
only, never modified) and adds the remaining, still-missing pieces of
DATA-02 — the concrete sample membership table, a venue calendar with
half-days (the existing ``TradingCalendar`` only models full trading days vs.
holidays/weekends), and the dated weekly-publish file format — in this
sibling package, ``universe_publish/``. Everything here composes with
``router.universe`` rather than re-implementing it.
"""

from __future__ import annotations
