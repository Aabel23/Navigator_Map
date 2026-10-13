"""One module per condition kind, each holding that kind's own rules.

The authoritative architecture names closures, flooding, construction and
incidents as four separate responsibilities, and they are -- what makes a
closure blocking is not what makes a flood blocking, and neither resembles how
an accident's severity is read. They are four modules rather than four
directories because each is one screen of rules; a directory per file would
make the repository look bigger without making any boundary clearer.

Every module here exposes one function that turns a normalized incident report
into a :class:`~roadstate.models.RoadCondition`, or ``None`` when the report
is not of that kind. :func:`roadstate.classify.classify` tries them in order.
"""

from .closures import as_closure
from .construction import as_construction
from .flooding import as_flooding
from .incidents import as_incident

__all__ = ["as_closure", "as_flooding", "as_construction", "as_incident"]
