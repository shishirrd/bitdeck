"""User-restricted, bounded single-instance handoff. Receives file names only."""
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

MAX_MESSAGE = 128 * 1024
SERVER_NAME = "BitDeck-" + hashlib.sha256(str(Path.home()).encode()).hexdigest()[:20]


def validate_message(data):
    if len(data) > MAX_MESSAGE:
        raise ValueError("Message too large")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")
    files = payload.get("files", [])
    workbench = payload.get("workbench", False)
    if not isinstance(files, list) or len(files) > 50 or any(not isinstance(path, str) or not path or "\x00" in path or len(path) > 32_000 for path in files) or type(workbench) is not bool:
        raise ValueError("Invalid handoff")
    return files, workbench


def handoff(files, workbench=False):
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(350):
        return False
    payload = json.dumps({"files": files, "workbench": workbench}).encode() + b"\n"
    if len(payload) > MAX_MESSAGE:
        socket.abort()
        return False
    socket.write(payload)
    success = socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.UnconnectedState:
        socket.waitForDisconnected(300)
    return success


class InstanceServer(QObject):
    requested = Signal(list, bool)

    def __init__(self, parent=None, name=SERVER_NAME):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self.accept)
        self.listening = self.server.listen(name)
        self.connections = set()

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if len(self.connections) >= 16:
                socket.abort()
                socket.deleteLater()
                continue
            self.connections.add(socket)
            socket.setReadBufferSize(MAX_MESSAGE + 1)
            buffer = bytearray()
            done = {"closed": False}
            timer = QTimer(socket, singleShot=True, interval=1500)

            def close(s=socket, t=timer, state=done):
                if state["closed"]:
                    return
                state["closed"] = True
                t.stop()
                self.connections.discard(s)
                s.abort()
                s.deleteLater()

            def read(s=socket, data=buffer, finish=close, state=done):
                if state["closed"]:
                    return
                data.extend(bytes(s.readAll()))
                if len(data) > MAX_MESSAGE:
                    finish()
                    return
                if not data.endswith(b"\n"):
                    return
                try:
                    files, workbench = validate_message(data)
                    self.requested.emit(files, workbench)
                except (ValueError, AttributeError):
                    pass
                finally:
                    finish()
            socket.readyRead.connect(read)
            socket.disconnected.connect(lambda s=socket: self.connections.discard(s))
            timer.timeout.connect(close)
            timer.start()
            read()

    def close(self):
        self.server.close()
        for socket in list(self.connections):
            socket.abort()
            socket.deleteLater()
        self.connections.clear()
