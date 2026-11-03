"""Four-player co-op. Importing this package opens no network resources.

The launcher explicitly owns discovery until it hands a started session to the
game. Rules, transport and Qt presentation are kept separate so they can be
exercised without a display or a listening socket.
"""

MAX_PLAYERS = 4
PROTOCOL_VERSION = 1
