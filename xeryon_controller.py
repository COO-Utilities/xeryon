"""HISPEC interface to Xeryon piezo motion controllers.

Wraps the vendored Xeryon library in the hardware_device_base interface the
other HISPEC drivers implement, so a daemon sees the same snake_case API it
gets from any other motion controller.

The vendored library polls the controller from a background thread and caches
what comes back, so every getter here reads that cache rather than talking to
the hardware.
"""

import time
from typing import Dict, List, Optional, Tuple, Union

from hardware_device_base import HardwareMotionBase

from .Xeryon import Axis, Stage, Units, Xeryon
from .tcp_communication import TcpCommunication

DEFAULT_BAUDRATE = 115200

#: How long connect() waits for the controller to start reporting positions
DEFAULT_DATA_TIMEOUT_S = 2.0

#: How long disconnect() waits for queued commands to go out, and for the
#: communication thread to finish
SEND_DRAIN_TIMEOUT_S = 1.0
THREAD_JOIN_TIMEOUT_S = 2.0

_POLL_INTERVAL_S = 0.05

#: Status bits worth reporting as an error, in the order they are reported
_FAULT_BITS = (
    ("encoder error", "isEncoderError"),
    ("error limit", "isErrorLimit"),
    ("thermal protection 1", "isThermalProtection1"),
    ("thermal protection 2", "isThermalProtection2"),
    ("safety timeout (TOU2)", "isSafetyTimeoutTriggered"),
    ("position fail (TOU3)", "isPositionFailTriggered"),
    ("end stop", "isEndStop"),
    ("emergency stop", "isEmergencyStop"),
)


class XeryonController(HardwareMotionBase):
    """Controller for one Xeryon XD controller and the axes on it."""

    def __init__(self, settings_file: Optional[str] = None,
                 log: bool = True, logfile: Optional[str] = None) -> None:
        """Create a controller.

        :param str settings_file: Settings file to load for this controller.
            Each controller needs its own, so this is worth setting even
            though the library falls back to a module-level default.
        :param bool log: If True, also log to file.
        :param str logfile: Filename to log to.
        """
        super().__init__(log=log, logfile=logfile)
        self.settings_file = settings_file
        self._controller: Optional[Xeryon] = None
        self._specs: List[Tuple[str, Stage, Units]] = []

    @property
    def letters(self) -> List[str]:
        """Return the configured axis letters, in the order they were added."""
        return [letter for letter, _, _ in self._specs]

    def add_axis(self, letter: str, stage: Union[str, Stage],
                 units: Union[str, Units] = "mm") -> None:
        """Declare an axis, before connecting.

        Every axis physically present has to be declared, including ones
        nothing is wired to, because the library matches the controller's
        replies to axes by position in this list.

        :param str letter: Axis letter as the controller names it, e.g. "A".
        :param stage: Stage enum member, or its name, or an encoder
            resolution command such as "XLS3=5".
        :param units: Units this axis reports and accepts, or their name.
        """
        if self.is_connected():
            raise RuntimeError("cannot add an axis while connected")
        letter = str(letter).upper()
        if letter in self.letters:
            raise ValueError(f"axis {letter} is already configured")
        self._specs.append((letter, resolve_stage(stage), resolve_units(units)))

    def connect(self, host: Optional[str] = None, port: Optional[int] = None,  # pylint: disable=W0221
                com_port: Optional[str] = None, baudrate: int = DEFAULT_BAUDRATE,
                do_reset: bool = False, send_settings: bool = False,
                data_timeout: float = DEFAULT_DATA_TIMEOUT_S) -> None:
        """Connect to the controller over TCP or USB serial.

        :param str host: Terminal server hostname or address.
        :param int port: Terminal server port.
        :param str com_port: Serial device, as an alternative to host/port.
        :param int baudrate: Baudrate, for a serial connection.
        :param bool do_reset: Reset the axes on connect. Off by default: a
            reset invalidates the encoder index, and a daemon reconnecting to
            a referenced stage should not silently cost it its reference.
        :param bool send_settings: Push the settings file to the controller.
            Off by default, leaving the controller on what it has in flash.
        :param float data_timeout: How long to wait for the controller to
            report a position before declaring the connection dead. 0 skips
            the check.
        """
        if not self._specs:
            raise RuntimeError("no axes configured; call add_axis() first")
        if self.is_connected():
            return
        if bool(host) == bool(com_port):
            raise ValueError("specify either host and port, or com_port")
        if host and port is None:
            raise ValueError("host given without port")

        controller = Xeryon(COM_port=com_port, baudrate=baudrate,
                            settings_filename=self.settings_file)
        if host:
            controller.comm = TcpCommunication(controller, host, int(port))
        for letter, stage, units in self._specs:
            controller.addAxis(stage, letter).setUnits(units)

        target = f"{host}:{port}" if host else com_port
        self.logger.info("Connecting to Xeryon controller at %s", target)
        controller.start(do_reset=do_reset, send_settings=send_settings)
        self._controller = controller
        self._set_connected(True)

        try:
            self._wait_for_data(data_timeout)
        except TimeoutError as e:
            self.disconnect()
            raise ConnectionError(f"no data from the controller at {target}: {e}") from e
        self.logger.info("Connected to Xeryon controller at %s", target)

    def disconnect(self) -> None:
        """Stop any motion and close the connection.

        Deliberately not the library's stop(), which also sends ZERO=0.
        """
        controller, self._controller = self._controller, None
        self._set_connected(False)
        if controller is None:
            return
        comm = controller.getCommunication()
        try:
            controller.stopMovements()
            # Closing without waiting here would drop the halt on the floor
            _drain_send_queue(comm, SEND_DRAIN_TIMEOUT_S)
        finally:
            comm.closeCommunication()
            if comm.thread is not None:
                comm.thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
        self.logger.info("Disconnected from Xeryon controller")

    def is_connected(self) -> bool:
        """Return whether the link to the controller is open."""
        if not self.connected or self._controller is None:
            return False
        comm = self._controller.getCommunication()
        return bool(comm.ser is not None and comm.ser.is_open and not comm.stop_thread)

    def home(self, letter: Optional[str] = None, blocking: bool = False) -> bool:  # pylint: disable=W0221
        """Search the encoder index, which is what references an axis.

        :param str letter: Axis letter, optional on a one-axis controller.
        :param bool blocking: Wait for the index to be found.
        :return: True if the index was found, or if the search was started
            and not waited for.
        """
        axis = self._axis(letter)
        if blocking:
            return bool(axis.findIndex(forceWaiting=True))
        axis.sendCommand("INDX=0")
        return True

    def is_homed(self, letter: Optional[str] = None) -> bool:  # pylint: disable=W0221
        """Return whether the axis has found its encoder index."""
        return bool(self._axis(letter).isEncoderValid())

    def get_pos(self, letter: Optional[str] = None) -> Optional[float]:  # pylint: disable=W0221
        """Return the encoder position, in the axis's units."""
        axis = self._axis(letter)
        if axis.getData("EPOS") is None:
            return None
        return float(axis.getEPOS())

    def set_pos(self, position: float, letter: Optional[str] = None,  # pylint: disable=W0221
                blocking: bool = False) -> bool:
        """Move to an absolute position, in the axis's units.

        :param float position: Target position.
        :param str letter: Axis letter, optional on a one-axis controller.
        :param bool blocking: Wait for the position to be reached.
        :return: True if the position was reached, or if the move was
            commanded and not waited for.
        """
        axis = self._axis(letter)
        if blocking:
            return bool(axis.setDPOS(position, forceWaiting=True))
        axis.sendCommand(f"DPOS={int(axis.convertUnitsToEncoder(position))}")
        return True

    def get_target_pos(self, letter: Optional[str] = None) -> Optional[float]:
        """Return the commanded position (DPOS), in the axis's units."""
        axis = self._axis(letter)
        if axis.getData("DPOS") is None:
            return None
        return float(axis.getDPOS())

    def is_moving(self, letter: Optional[str] = None) -> bool:
        """Return whether the axis is driving towards a position.

        The position-reached bit stays low after a halt, so on its own it
        cannot tell a move in progress from one that was abandoned; the
        motor-on bit is what separates the two.
        """
        axis = self._axis(letter)
        if axis.getData("STAT") is None:
            return False
        return bool(axis.isMotorOn()) and not bool(axis.isPositionReached())

    def close_loop(self, letter: Optional[str] = None, enable: bool = True) -> bool:  # pylint: disable=W0221
        """Enable or disable closed-loop control (ENBL) on the axis."""
        self._axis(letter).sendCommand(f"ENBL={1 if enable else 0}")
        return True

    def is_loop_closed(self, letter: Optional[str] = None) -> bool:  # pylint: disable=W0221
        """Return whether the axis is under closed-loop control."""
        return bool(self._axis(letter).isClosedLoop())

    def stop(self, letter: Optional[str] = None) -> None:
        """Halt one axis, or every axis when no letter is given."""
        axes = [self._axis(letter)] if letter is not None else self._all_axes()
        for axis in axes:
            axis.sendCommand("STOP=0")

    def flush_commands(self, timeout: float = SEND_DRAIN_TIMEOUT_S) -> bool:
        """Wait for queued commands to reach the controller.

        Commands are written by the library's communication thread, so a
        caller that has to know a command is on the wire (a halt before
        disconnecting, say) has to wait for it.

        :return: True if the queue drained within the timeout.
        """
        comm = self._require_controller().getCommunication()
        return _drain_send_queue(comm, timeout)

    def get_limits(self) -> Optional[Dict[str, Tuple[float, float]]]:
        """Return each axis's travel limits, in that axis's units.

        These come from the settings file rather than the controller, which
        only reports them back when echo is on.
        """
        limits: Dict[str, Tuple[float, float]] = {}
        for axis in self._all_axes():
            low = self._limit(axis, "LLIM")
            high = self._limit(axis, "HLIM")
            if low is not None and high is not None:
                limits[axis.getLetter()] = (low, high)
        return limits or None

    def get_last_error(self, letter: Optional[str] = None) -> str:
        """Return the axis's active fault bits, or an empty string if clean."""
        axis = self._axis(letter)
        if axis.getData("STAT") is None:
            return "no status received from the controller"
        faults = [name for name, check in _FAULT_BITS if getattr(axis, check)()]
        return ", ".join(faults)

    def get_units(self, letter: Optional[str] = None) -> str:
        """Return the name of the units the axis reports."""
        return self._axis(letter).getUnit().name

    def _send_command(self, command: str, letter: Optional[str] = None) -> bool:  # pylint: disable=W0221
        """Queue a raw "TAG=value" command for an axis, or for the controller
        itself when no letter is given."""
        with self.lock:
            if letter is None:
                self._require_controller().getCommunication().sendCommand(command)
            else:
                self._axis(letter).sendCommand(command)
        return True

    def _read_reply(self) -> None:
        """Replies are not read here.

        The library's communication thread reads every reply and files it
        into the per-axis cache, which is what the getters above read.
        """
        return None

    def _require_controller(self) -> Xeryon:
        if self._controller is None:
            raise RuntimeError("not connected")
        return self._controller

    def _all_axes(self) -> List[Axis]:
        return list(self._require_controller().getAllAxis())

    def _axis(self, letter: Optional[str]) -> Axis:
        controller = self._require_controller()
        if letter is None:
            axes = controller.getAllAxis()
            if len(axes) != 1:
                raise ValueError(
                    f"this controller has {len(axes)} axes; name one of "
                    f"{self.letters}")
            return axes[0]
        axis = controller.getAxis(str(letter).upper())
        if axis is None:
            raise ValueError(f"unknown axis {letter!r}; configured: {self.letters}")
        return axis

    @staticmethod
    def _limit(axis: Axis, tag: str) -> Optional[float]:
        value = axis.getSetting(tag)
        if value is None:
            return None
        return float(axis.convertEncoderUnitsToUnits(value))

    def _wait_for_data(self, timeout: float) -> None:
        """Block until every axis has reported a position.

        A terminal server accepts the connection whether or not the
        controller behind it is powered, so this is what tells the two apart.
        """
        if timeout <= 0:
            return
        deadline = time.monotonic() + timeout
        while True:
            silent = [axis.getLetter() for axis in self._all_axes() if axis.update_nb == 0]
            if not silent:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"axes {silent} reported nothing within {timeout}s; check that the "
                    "controller is powered and that its POLI setting is non-zero")
            time.sleep(_POLL_INTERVAL_S)


def _drain_send_queue(comm, timeout: float) -> bool:
    """Wait for the communication thread to write out what it has queued."""
    deadline = time.monotonic() + timeout
    while comm.readyToSend:
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_INTERVAL_S)
    return True


def resolve_stage(stage: Union[str, Stage]) -> Stage:
    """Return the Stage member named ``stage``, or matching its encoder
    resolution command (e.g. "XLS3=5")."""
    if isinstance(stage, Stage):
        return stage
    name = str(stage).strip()
    if name in Stage.__members__:
        return Stage[name]
    # Matched exactly rather than via Stage.getStage(), whose substring match
    # resolves "XLS3=1" to the XLS3=1251 stage
    command = name.replace(" ", "")
    for member in Stage:
        if command == str(member.encoderResolutionCommand).replace(" ", ""):
            return member
    raise ValueError(
        f"unknown stage {stage!r}; expected one of {list(Stage.__members__)} "
        "or an encoder resolution command such as 'XLS3=5'")


def resolve_units(units: Union[str, Units]) -> Units:
    """Return the Units member named ``units``."""
    if isinstance(units, Units):
        return units
    name = str(units).strip()
    if name not in Units.__members__:
        raise ValueError(
            f"unknown units {units!r}; expected one of {list(Units.__members__)}")
    return Units[name]
