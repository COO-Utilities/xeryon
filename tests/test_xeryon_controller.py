"""Tests for XeryonController, against a fake controller port."""

import threading
import time
from collections import deque

import pytest

from xeryon import Stage, Units, XeryonController
from xeryon.tcp_communication import TcpCommunication
from xeryon.xeryon_controller import resolve_stage, resolve_units

# 5 nm encoder resolution: 1 mm is 200000 encoder units
ENCODER_UNITS_PER_MM = 200_000

# Bit 5 (motor on), bit 8 (encoder valid), bit 10 (position reached)
STAT_IDLE_REFERENCED = (1 << 5) | (1 << 8) | (1 << 10)

POLL_PERIOD_S = 0.01

SETTINGS = """
POLI=97

A:LLIM=-25
A:HLIM=25
A:SSPD=5
B:LLIM=-12.5
B:HLIM=12.5
B:SSPD=5
"""


class FakePort:
    """Stand-in for the controller's port, replaying a fixed status."""

    def __init__(self, letters, stat=STAT_IDLE_REFERENCED, epos=0, silent=False):
        self.is_open = True
        self.written = []
        self.stat = stat
        self.silent = silent
        self._letters = list(letters)
        self._epos = {letter: epos for letter in self._letters}
        self._pending = deque()
        self._next_round = 0.0
        self._lock = threading.Lock()

    @property
    def in_waiting(self):
        """Return the bytes available, generating a status round when due.

        Paced like a real port, whose read timeout is what keeps the
        library's communication thread from spinning flat out.
        """
        with self._lock:
            due = time.monotonic() >= self._next_round
            if not self._pending and not self.silent and due:
                self._next_round = time.monotonic() + POLL_PERIOD_S
                for letter in self._letters:
                    self._pending.append(f"{letter}:EPOS={self._epos[letter]}\n")
                    self._pending.append(f"{letter}:STAT={self.stat}\n")
            pending = sum(len(line) for line in self._pending)
        if not pending:
            time.sleep(POLL_PERIOD_S / 4)
        return pending

    def write(self, data):
        """Record a command and apply the ones the fake understands."""
        command = data.decode().strip()
        with self._lock:
            self.written.append(command)
            letter, _, body = command.partition(":")
            tag, _, value = body.partition("=")
            if tag == "DPOS" and letter in self._epos:
                self._epos[letter] = int(value)
        return len(data)

    def readline(self):
        """Return the next queued line from the controller."""
        with self._lock:
            return self._pending.popleft().encode() if self._pending else b""

    def commands(self, tag):
        """Return every command written for the given tag."""
        with self._lock:
            return [c for c in self.written if c.partition(":")[2].startswith(f"{tag}=")
                    or c.startswith(f"{tag}=")]

    def flush(self):
        """Accept the serial API; nothing is buffered."""

    def reset_input_buffer(self):
        """Accept the serial API; drop anything queued."""
        with self._lock:
            self._pending.clear()

    def reset_output_buffer(self):
        """Accept the serial API; nothing is buffered."""

    def close(self):
        """Close the port."""
        self.is_open = False


@pytest.fixture(name="settings_file")
def settings_file_fixture(tmp_path):
    """Write a two-axis settings file and return its path."""
    path = tmp_path / "settings.txt"
    path.write_text(SETTINGS, encoding="utf-8")
    return str(path)


@pytest.fixture(name="connect")
def connect_fixture(monkeypatch, settings_file):
    """Return a factory connecting a controller to a FakePort."""
    created = []

    def _connect(port=None, **kwargs):
        port = port if port is not None else FakePort("AB")
        monkeypatch.setattr(TcpCommunication, "openPort", lambda self: port)
        controller = XeryonController(settings_file=settings_file, log=False)
        controller.add_axis("A", Stage.XLS_5_3N, units="mm")
        controller.add_axis("B", Stage.XLS_5_3N, units="mm")
        created.append(controller)
        controller.connect(host="127.0.0.1", port=10001, **kwargs)
        return controller, port

    yield _connect

    for controller in created:
        controller.disconnect()


def test_connect_reports_connected(connect):
    controller, _ = connect()
    assert controller.is_connected()
    assert controller.letters == ["A", "B"]


def test_connect_without_reset_sends_no_reset(connect):
    _, port = connect()
    assert port.commands("RSET") == []


def test_connect_with_reset_sends_reset(connect):
    _, port = connect(do_reset=True)
    assert port.commands("RSET") == ["A:RSET=0", "B:RSET=0"]


def test_connect_without_send_settings_leaves_controller_alone(connect):
    _, port = connect()
    # The queries start() sends are fine; pushing a value from the file is not
    assert port.commands("SSPD") == ["A:SSPD=?", "B:SSPD=?"]


def test_connect_refuses_to_push_settings_over_tcp(connect):
    with pytest.raises(ValueError, match="does not work over the terminal server"):
        connect(send_settings=True)


def test_connect_does_not_enable_the_amplifiers(connect):
    _, port = connect()
    assert port.commands("ENBL") == []


def test_connect_raises_when_the_controller_is_silent(monkeypatch, settings_file):
    port = FakePort("AB", silent=True)
    monkeypatch.setattr(TcpCommunication, "openPort", lambda self: port)
    controller = XeryonController(settings_file=settings_file, log=False)
    controller.add_axis("A", Stage.XLS_5_3N)
    controller.add_axis("B", Stage.XLS_5_3N)

    with pytest.raises(ConnectionError):
        controller.connect(host="127.0.0.1", port=10001, data_timeout=0.2)
    assert not controller.is_connected()


def test_get_pos_converts_to_millimeters(connect):
    controller, _ = connect(port=FakePort("AB", epos=2 * ENCODER_UNITS_PER_MM))
    assert controller.get_pos("A") == pytest.approx(2.0)


def test_set_pos_commands_encoder_units(connect):
    controller, port = connect()
    controller.set_pos(-1.5, "B")
    assert controller.flush_commands()
    assert f"B:DPOS={-1.5 * ENCODER_UNITS_PER_MM:.0f}" in port.written


def test_home_starts_an_index_search(connect):
    controller, port = connect()
    controller.home("A")
    assert controller.flush_commands()
    assert "A:INDX=0" in port.written


def test_stop_without_a_letter_halts_every_axis(connect):
    controller, port = connect()
    controller.stop()
    assert controller.flush_commands()
    assert port.commands("STOP") == ["A:STOP=0", "B:STOP=0"]


def test_status_reflects_the_status_word(connect):
    controller, _ = connect()
    assert controller.is_homed("A")
    assert not controller.is_moving("A")
    assert not controller.is_loop_closed("A")
    assert controller.get_last_error("A") == ""


def test_moving_while_the_motor_drives_an_unreached_position(connect):
    # Motor on, encoder valid, position not reached
    controller, _ = connect(port=FakePort("AB", stat=(1 << 5) | (1 << 8)))
    assert controller.is_moving("A")


def test_last_error_names_the_active_faults(connect):
    # Bit 12 (encoder error) and bit 16 (error limit)
    controller, _ = connect(port=FakePort("AB", stat=(1 << 12) | (1 << 16)))
    assert controller.get_last_error("A") == "encoder error, error limit"


def test_limits_come_back_in_millimeters(connect):
    controller, _ = connect()
    assert controller.get_limits() == {"A": (-25.0, 25.0), "B": (-12.5, 12.5)}


def test_disconnect_halts_without_zeroing(connect):
    controller, port = connect()
    controller.disconnect()
    assert port.commands("STOP") == ["A:STOP=0", "B:STOP=0"]
    assert port.commands("ZERO") == []
    assert not controller.is_connected()


def test_unknown_axis_is_rejected(connect):
    controller, _ = connect()
    with pytest.raises(ValueError, match="unknown axis"):
        controller.get_pos("Z")


def test_connect_requires_one_transport(settings_file):
    controller = XeryonController(settings_file=settings_file, log=False)
    controller.add_axis("A", Stage.XLS_5_3N)
    with pytest.raises(ValueError, match="either host and port"):
        controller.connect()


def test_connect_requires_an_axis(settings_file):
    controller = XeryonController(settings_file=settings_file, log=False)
    with pytest.raises(RuntimeError, match="no axes configured"):
        controller.connect(host="127.0.0.1", port=10001)


@pytest.mark.parametrize("value,expected", [
    ("XLS_5_3N", Stage.XLS_5_3N),
    ("XLS3=5", Stage.XLS_5_3N),
    (Stage.XLS_1_3N, Stage.XLS_1_3N),
])
def test_resolve_stage_accepts_names_and_commands(value, expected):
    assert resolve_stage(value) is expected


def test_resolve_stage_rejects_the_unknown():
    with pytest.raises(ValueError, match="unknown stage"):
        resolve_stage("XLS_5_9000")


def test_resolve_units_accepts_names():
    assert resolve_units("mm") is Units.mm
    with pytest.raises(ValueError, match="unknown units"):
        resolve_units("furlongs")
