"""The map/routing/traffic simulator.

A sandbox, not a block. It owns no domain rule of its own: everything it does
is wire three server blocks together through their published interfaces and
show the result, so that the connectors between them can be exercised by hand.
"""
