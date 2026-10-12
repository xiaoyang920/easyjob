"""Run unit tests with a process-wide socket/DNS prohibition installed first."""
import json
import sys
import traceback
import unittest
import socket
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'python-agent'))
sys.path.insert(0, str(root / 'python-agent' / 'tests'))
attempts = []
current_test = ''


def deny_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo', 'socket.sendto'):
        # Windows asyncio implements its local wakeup pipe with socketpair().
        # Allow only that standard-library call, never application connections.
        frames = traceback.extract_stack()
        local_pair = len(args) > 1 and isinstance(args[1], tuple) and args[1][0] in ('127.0.0.1', '::1')
        if event == 'socket.connect' and local_pair and any(frame.name in ('socketpair', '_fallback_socketpair')
            and Path(frame.filename).resolve() == Path(socket.__file__).resolve() for frame in frames):
            return
        attempts.append({'test': current_test, 'event': event,
            'frames': [f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in frames[-10:-1]]})
        raise OSError('Offline unit tests prohibit all socket/DNS access')


class OfflineResult(unittest.TextTestResult):
    def startTest(self, test):
        global current_test
        current_test = test.id()
        super().startTest(test)


if __name__ == '__main__':
    # Audit hooks cannot be removed by an accidentally unmocked API client.
    sys.addaudithook(deny_network)
    suite = unittest.defaultTestLoader.discover(str(root / 'python-agent' / 'tests'))
    result = unittest.TextTestRunner(verbosity=2 if '-v' in sys.argv else 1, resultclass=OfflineResult).run(suite)
    print(json.dumps({'tests': result.testsRun, 'blocked_network_attempts': attempts}, ensure_ascii=False))
    raise SystemExit(0 if result.wasSuccessful() and not attempts else 1)
