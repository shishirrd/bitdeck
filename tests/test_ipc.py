import json
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket

from bitdeck.ipc import InstanceServer, MAX_MESSAGE, validate_message


def test_valid_handoff_schema():
    assert validate_message(b'{"files":["C:/example/file.pdf"],"workbench":false}\n') == (["C:/example/file.pdf"], False)


@pytest.mark.parametrize("value", [[], {"files": "path"}, {"files": [None]}, {"files": ["bad\x00path"]},
                                   {"files": ["file"] * 51}, {"workbench": "yes"}])
def test_invalid_handoff_schema_rejected(value):
    with pytest.raises(ValueError):
        validate_message(json.dumps(value).encode())


def test_oversized_handoff_rejected():
    with pytest.raises(ValueError):
        validate_message(b" " * (MAX_MESSAGE + 1))


def test_live_user_restricted_handoff():
    application = QCoreApplication.instance() or QCoreApplication([])
    server = InstanceServer(name="BitDeck-ipc-test-" + str(time.time_ns()))
    if not server.listening:
        pytest.skip("User-only named pipe unavailable: " + server.server.errorString())
    received = []
    server.requested.connect(lambda files, workbench: received.append((files, workbench)))
    client = QLocalSocket()
    try:
        client.connectToServer(server.server.serverName())
        assert client.waitForConnected(1000)
        client.write(b'{"files":["C:/example/input.pdf"],"workbench":false}\n')
        client.flush()
        deadline = time.monotonic() + 3
        while not received and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(.01)
        assert received == [(["C:/example/input.pdf"], False)]
    finally:
        client.abort()
        server.close()
