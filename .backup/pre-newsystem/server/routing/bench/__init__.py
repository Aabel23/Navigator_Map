"""Performance harness for the routing block.

Not production, and not part of the contract. Kept out of `routing/` so that
nothing shippable can import it, and out of `tests/` so that a normal `pytest`
run does not spend its time measuring.
"""
