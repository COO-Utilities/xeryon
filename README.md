# Xeryon Motion Controller Library

This module provides a Python interface to communicate with and control Xeryon precision stages. It supports serial communication, axis movement, settings management, and safe handling of errors and edge cases.

## Features
- Serial or TCP/IP communication with Xeryon controllers
- Multi-axis system support
- Configurable stage settings from a file
- Blocking/non-blocking movement
- Real-time data logging and error monitoring
- Configurable output via logger

---

## Getting Started
### Prerequisites
- Python 3.7+
- Xeryon controller connected via serial
- `pyserial` library


### Example Usage
#### Serial Connection
```python
from xeryon.controller import Xeryon
from xeryon.stage import Stage

# Initialize 3-axis controller
controller = Xeryon(COM_port="/dev/ttyACM0")
# All axes must be added, even if not all will be used
controller.addAxis(Stage.XLS_5_3N, "A")
controller.addAxis(Stage.XLS_5_3N, "B")
controller.addAxis(Stage.XLS_5_3N, "C")
# external_settings_default - used to point to the right settings file
controller.start(external_settings_default=None)

# Move axis
A_axis = controller.getAxis("A")
A_axis.setDPOS(1)  # Move to position 1 in current units

controller.stop()
```

#### TCP Connection
```python
from xeryon import Tcp_xeryon
from xeryon import Stage

# Initialize controller
controller = Tcp_xeryon(tcp_address="127.0.0.1", tcp_port=10001)
# All axes must be added, even if not all will be used
controller.addAxis(Stage.XLS_5_3N, "A")
controller.addAxis(Stage.XLS_5_3N, "B")
controller.addAxis(Stage.XLS_5_3N, "C")
# external_settings_default - used to point to the right settings file
controller.start(external_settings_default=None)

# Move axis
A_axis = controller.getAxis("A")
A_axis.setDPOS(1)  # Move to position 1000 in current units

controller.stop()
```


## Settings File
Place a `settings.txt` file in the config directory. Format:
```txt
A:LLIM=0
A:HLIM=100000
A:SSPD=2000
POLI=5
```
Each line sets a controller or axis setting.

---

## Logging
The `utils.py` module provides a `output_console` function with logger integration. Messages can be printed to stdout or stderr depending on severity.
