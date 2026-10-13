"""A navigation demo built on the server's public API.

Not a block. It owns no domain rule and computes nothing: it draws the client
map block's real renderer, and everything it shows -- the route, the turns, the
traffic, the closures -- comes from `/api/v1`. The point is to show what the
server can already do, using only what a phone could use.
"""
