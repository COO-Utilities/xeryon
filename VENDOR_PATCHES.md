# Vendored Xeryon library

`Xeryon.py` is the vendor's library, copied in with as few changes as possible so it stays
diffable against future releases. Its camelCase API and formatting are left alone even where
they clash with the surrounding code; the HISPEC-facing API lives in `xeryon_controller.py`.

Source: https://github.com/Xeryon-Precision/XD-M_Code_Examples/blob/main/Examples/Python/USB/Xeryon.py
Vendored: 2026-09-16, library version v2.0

## Refreshing

Copy the new upstream file over `Xeryon.py`, replay the patches below, and run the tests. Every
patched line is marked `(HISPEC)` in a comment or docstring, so `grep -n HISPEC Xeryon.py` finds
them all.

## Patches

1. `Xeryon.start(do_reset=True, send_settings=None, enable_axes=True)`.

   `do_reset=False` skips the per-axis reset, which is what lets a daemon reconnect to a
   referenced stage without invalidating its encoder index and forcing a re-reference.

   `send_settings=False` loads the settings file into the library's cache, so unit conversion and
   travel limits are known, without pushing it to a controller that already has those settings in
   flash. Pushing them does not work over a terminal server at all, so `XeryonController` refuses
   it outright on a TCP connection; configure a controller over USB with the Xeryon interface.

   `enable_axes=False` leaves the amplifiers alone rather than sending `ENBL=1`. Closing the loop
   on an axis whose commanded position differs from where it sits makes it drive there, which
   connecting has no business deciding.

   All three default to upstream behavior.

2. `Communication.openPort()`.

   The serial port construction moved out of `Communication.start()` into a method, so
   `TcpCommunication` in `tcp_communication.py` can serve a socket instead of duplicating the
   class. Upstream behavior is unchanged.

3. `outputConsole()` and the communication thread log instead of printing.

   A daemon needs the library's faults and its "communication thread crashed" message in its own
   log rather than on stdout. Messages go through a module-level `logging` logger; the
   `OUTPUT_TO_CONSOLE` and `OUTPUT_CONSOLE_TIMESTAMPS` flags still apply.
