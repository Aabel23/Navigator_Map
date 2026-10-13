"""Puts the server root on ``sys.path`` so every block imports by its own name.

``server/`` is a path root, not a package: ``routing``, ``mapdata``, ``traffic``,
``roadstate``, ``ingest``, ``storage``, ``api``, ``domain``, ``config`` and
``observability`` are top-level modules. That keeps each block importable on its
own -- a routing test needs nothing but this directory on the path -- while the
composition root in ``api/app.py`` can still reach all of them.

Belt and braces alongside ``pytest.ini``: this file works even when pytest is
invoked from elsewhere, or with a configuration file that does not apply.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
