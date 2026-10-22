"""Make sure only one HangulFlow runs; a second launch just shows the first one's widget.

A QLockFile is the real guard (it detects stale locks left by a crash). A local
socket lets the second launch ask the running instance to show itself.
"""

from __future__ import annotations

import getpass
import logging
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, lock_file: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = QLockFile(str(lock_file))
        self._lock.setStaleLockTime(0)  # only stale if the owning process is gone
        self._server_name = f"HangulFlow-{getpass.getuser()}"
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """True if this process is the primary instance."""
        if not self._lock.tryLock(200):
            self._notify_primary()
            return False
        QLocalServer.removeServer(self._server_name)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if self._server.listen(self._server_name):
            self._server.newConnection.connect(self._on_new_connection)
        else:
            log.warning("Single-instance server could not listen: %s", self._server.errorString())
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
        self._lock.unlock()

    def _notify_primary(self) -> None:
        socket = QLocalSocket()
        socket.connectToServer(self._server_name)
        if socket.waitForConnected(500):
            socket.write(b"show")
            socket.flush()
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()

    def _on_new_connection(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            connection.disconnected.connect(connection.deleteLater)
            connection.disconnectFromServer()
            self.activation_requested.emit()
