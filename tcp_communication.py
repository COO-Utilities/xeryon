"""TCP transport for the vendored Xeryon library.

Xeryon controllers speak the same line protocol over USB serial and over a
serial-to-Ethernet terminal server. This module provides the socket half so
`Xeryon.Communication` can be used unchanged against either one.
"""

import socket
from typing import Optional

from .Xeryon import Communication

DEFAULT_CONNECT_TIMEOUT_S = 5.0
DEFAULT_READ_TIMEOUT_S = 0.01


class SocketPort:
    """Serial-like view of a TCP socket, exposing what Communication uses."""

    def __init__(self, host: str, port: int,
                 read_timeout: float = DEFAULT_READ_TIMEOUT_S,
                 connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_S) -> None:
        self._socket: Optional[socket.socket] = socket.create_connection(
            (host, port), timeout=connect_timeout)
        self._socket.settimeout(read_timeout)
        self._buffer = bytearray()

    @property
    def is_open(self) -> bool:
        """Return whether the socket is still usable."""
        return self._socket is not None

    @property
    def in_waiting(self) -> int:
        """Return the number of bytes in *complete* buffered lines.
        
        Complete lines are those terminated with a newline char.
        This is to ensure that message fragments are not passed to the 
        calling parent function. Fragments, if not parsed correctly 
        downstream, can lead to incorrect message interpretation (eg. 
        incorrect STAT values and incorrect position values, etc.)
        """
        self._fill()
        return self._buffer.rfind(b"\n") + 1

    def write(self, data: bytes) -> int:
        """Send ``data`` to the controller."""
        if self._socket is None:
            raise OSError("write on a closed socket")
        self._socket.sendall(data)
        return len(data)

    def readline(self) -> bytes:
        """Return one complete buffered line including its newline, or b""
        if only a partial line has arrived so far."""
        if b"\n" not in self._buffer:
            self._fill()
        newline = self._buffer.find(b"\n")
        if newline < 0:
            return b""
        line = bytes(self._buffer[:newline + 1])
        del self._buffer[:newline + 1]
        return line

    def flush(self) -> None:
        """Present for serial compatibility; sends are never buffered here."""

    def reset_input_buffer(self) -> None:
        """Drop anything received but not yet read."""
        self._buffer.clear()

    def reset_output_buffer(self) -> None:
        """Present for serial compatibility; sends are never buffered here."""

    def close(self) -> None:
        """Close the socket, if it is still open."""
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _fill(self) -> None:
        """Read whatever has arrived into the buffer without blocking."""
        if self._socket is None:
            return
        while True:
            try:
                chunk = self._socket.recv(4096)
            except (socket.timeout, BlockingIOError):
                return
            except OSError:
                self.close()
                return
            if not chunk:
                # The far end closed; without this the read loop would spin
                # on an empty socket that is never going to produce data
                self.close()
                return
            self._buffer.extend(chunk)
            if len(chunk) < 4096:
                return


class TcpCommunication(Communication):
    """Communication that reaches the controller over a terminal server."""

    def __init__(self, xeryon_object, host: str, port: int) -> None:
        # COM_port doubles as the label in the library's own error messages,
        # and leaving it None would send Communication.start() port-hunting
        super().__init__(xeryon_object, f"{host}:{port}", baud=0)
        self.host = host
        self.port = int(port)
        self.read_timeout = DEFAULT_READ_TIMEOUT_S
        self.connect_timeout = DEFAULT_CONNECT_TIMEOUT_S

    def openPort(self) -> SocketPort:  # noqa: N802  (vendor library naming)
        """Open the socket the communication thread reads and writes."""
        return SocketPort(self.host, self.port,
                          read_timeout=self.read_timeout,
                          connect_timeout=self.connect_timeout)
