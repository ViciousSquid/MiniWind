"""Four-player co-op, with AI companions on top. Importing this package opens no network resources.

The launcher explicitly owns discovery until it hands a started session to the
game. Rules, transport and Qt presentation are kept separate so they can be
exercised without a display or a listening socket.
"""

#: Human players in a party, at most; AI companions come on top of them.
MAX_PLAYERS = 4
MAX_COMPANIONS = 4
MAX_PARTY = MAX_PLAYERS + MAX_COMPANIONS
PROTOCOL_VERSION = 1
