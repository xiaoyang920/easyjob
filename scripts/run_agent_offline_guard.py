"""Reusable replay guard. Only asyncio's Windows socketpair wakeup is allowed."""
import socket
import sys
import traceback
from pathlib import Path


def install():
    def deny(event, args):
        if event not in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
            return
        frames = traceback.extract_stack()
        local_pair = len(args)>1 and isinstance(args[1], tuple) and args[1][0] in ('127.0.0.1', '::1')
        if event == 'socket.connect' and local_pair and any(frame.name in ('socketpair', '_fallback_socketpair')
            and Path(frame.filename).resolve() == Path(socket.__file__).resolve() for frame in frames):
            return
        raise OSError('Replay evaluation prohibits network calls')
    sys.addaudithook(deny)
