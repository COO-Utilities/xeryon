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

# Initialize controller
controller = Xeryon(COM_port="/dev/ttyUSB0")
controller.addAxis(Stage.XLS_312, "X")
controller.start()

# Move axis
x_axis = controller.getAxis("X")
x_axis.setDPOS(1000)  # Move to position 1000 in current units

controller.stop()
```

#### TCP Connection
```python
from xeryon import Tcp_xeryon
from xeryon import Stage

# Initialize controller
controller = Tcp_xeryon(tcp_address="127.0.0.1", tcp_port=10001)
controller.addAxis(Stage.XLS_312, "X")
controller.start()

# Move axis
x_axis = controller.getAxis("X")
x_axis.setDPOS(1000)  # Move to position 1000 in current units

controller.stop()
```


## Settings File
Place a `settings.txt` file in the config directory. Format:
```txt
X:LLIM=0
X:HLIM=100000
X:SSPD=2000
POLI=5
```
Each line sets a controller or axis setting.

---

## Logging
The `utils.py` module provides a `output_console` function with logger integration. Messages can be printed to stdout or stderr depending on severity.
