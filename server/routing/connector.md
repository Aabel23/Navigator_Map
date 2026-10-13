# routing -- Connector

The authoritative connector for this block is
[`agent-system-server/blocks/routing/connector.md`](../../agent-system-server/blocks/routing/connector.md).

It is kept there with every other block's connector so there is one place
to read the boundaries and one place to change them. This file is a
pointer rather than a copy, because two statements of one interface is two
things to keep in sync and a guarantee that somebody eventually reads the
wrong one.

The v1.0 guarantees themselves stay here, in [`contract.md`](contract.md),
because they are enforced by [`tests/contract/test_v1.py`](tests/contract/test_v1.py)
and belong next to the suite that proves them.
