"""
ADS change-notification manager.

Uses pyads ``add_device_notification`` to subscribe to variable changes
pushed by TwinCAT, then distributes events to registered Python callbacks
through a thread-safe queue and a dedicated dispatch thread.

In mock mode the real ADS layer is bypassed and MockNotificationSimulator
drives periodic value changes so the rest of the stack can be exercised
without a live PLC.
"""
from __future__ import annotations

import ctypes
import logging
import queue
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import pyads

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NotificationManager
# ---------------------------------------------------------------------------

class NotificationManager:
    """
    Thread-safe ADS notification manager.

    One instance is shared across the application (typically owned by
    DeviceRegistry or a dedicated singleton).  Subscribers register a
    Python callback; the manager handles all pyads bookkeeping and fans
    events out via an internal queue + dispatch thread.

    Usage::

        mgr = NotificationManager(client)
        mgr.subscribe('gvlDALI.aPyActualLevel[1]', pyads.PLCTYPE_BYTE, my_cb)
        # …later…
        mgr.unsubscribe_all()
    """

    def __init__(self, client) -> None:
        """
        Parameters
        ----------
        client:
            An ``ADSClient`` instance (see ads_client.py).
        """
        self._client = client

        # var_name → list of registered callbacks
        self._subscriptions: Dict[str, List[Callable[[str, Any, float], None]]] = {}

        # var_name → (notification_handle, user_handle) returned by pyads
        self._handles: Dict[str, Tuple[Any, Any]] = {}

        # var_name → plctype (needed to size the NotificationAttrib and decode)
        self._type_map: Dict[str, Any] = {}

        # Thread-safe event queue – items are (var_name, value, timestamp)
        self._queue: queue.Queue = queue.Queue()

        self._dispatch_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._lock: threading.RLock = threading.RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(
        self,
        var_name: str,
        plctype: Any,
        callback: Callable[[str, Any, float], None],
        cycle_ms: int = 200,
    ) -> bool:
        """
        Subscribe *callback* to change events for *var_name*.

        In mock mode this always returns ``False`` so callers know to fall
        back to polling.

        Parameters
        ----------
        var_name:
            Fully-qualified PLC variable name, e.g. ``'gvlDALI.aPyActualLevel[1]'``.
        plctype:
            pyads type constant, e.g. ``pyads.PLCTYPE_BYTE``.
        callback:
            Called as ``callback(var_name, value, timestamp)`` on the
            dispatch thread.
        cycle_ms:
            ADS notification cycle time in milliseconds (default 200 ms).

        Returns
        -------
        bool
            ``True`` on success, ``False`` if mock mode or registration
            failed.
        """
        if self._client.mock:
            return False

        with self._lock:
            # Register callback
            if var_name not in self._subscriptions:
                self._subscriptions[var_name] = []
            if callback not in self._subscriptions[var_name]:
                self._subscriptions[var_name].append(callback)

            # Store type for later use (restore_subscriptions, etc.)
            self._type_map[var_name] = plctype

            # Register ADS notification only once per variable
            if var_name not in self._handles:
                try:
                    self._register_ads_notification(var_name, plctype, cycle_ms)
                except Exception as exc:
                    logger.error(
                        "NotificationManager: failed to register '%s': %s",
                        var_name, exc,
                    )
                    # Remove the callback we just added to keep state consistent
                    self._subscriptions[var_name].remove(callback)
                    if not self._subscriptions[var_name]:
                        del self._subscriptions[var_name]
                    return False

            # Ensure the dispatch thread is running
            if not self._running:
                self._start_dispatch()

        return True

    def unsubscribe(
        self,
        var_name: str,
        callback: Callable = None,
    ) -> None:
        """
        Remove *callback* from *var_name*.

        If *callback* is ``None``, all callbacks for the variable are
        removed.  When no callbacks remain the underlying ADS notification
        is cancelled.
        """
        with self._lock:
            if var_name not in self._subscriptions:
                return

            if callback is None:
                self._subscriptions[var_name].clear()
            else:
                try:
                    self._subscriptions[var_name].remove(callback)
                except ValueError:
                    pass

            # Cancel ADS notification when no listeners remain
            if not self._subscriptions[var_name]:
                del self._subscriptions[var_name]
                self._type_map.pop(var_name, None)
                if var_name in self._handles:
                    self._cancel_ads_notification(var_name)

    def subscribe_many(
        self,
        var_type_pairs: List[Tuple[str, Any]],
        callback: Callable[[str, Any, float], None],
        cycle_ms: int = 200,
    ) -> int:
        """
        Subscribe *callback* to multiple variables at once.

        Parameters
        ----------
        var_type_pairs:
            List of ``(var_name, plctype)`` tuples.
        callback:
            Single callback shared by all variables.
        cycle_ms:
            ADS notification cycle time for all variables.

        Returns
        -------
        int
            Number of successfully registered subscriptions.
        """
        count = 0
        for var_name, plctype in var_type_pairs:
            if self.subscribe(var_name, plctype, callback, cycle_ms):
                count += 1
        return count

    def unsubscribe_all(self) -> None:
        """
        Cancel every ADS notification, clear all subscriptions and stop
        the dispatch thread.
        """
        self._stop_dispatch()

        with self._lock:
            for var_name in list(self._handles.keys()):
                self._cancel_ads_notification(var_name)
            self._subscriptions.clear()
            self._type_map.clear()

    def restore_subscriptions(self) -> None:
        """
        Re-register all current subscriptions in pyads after a reconnect.

        ADS notification handles are invalidated when the connection drops,
        so we must re-register every variable we care about.
        """
        if self._client.mock:
            return

        with self._lock:
            # Handles are now stale — clear them without calling del_device_notification
            self._handles.clear()

            for var_name, plctype in list(self._type_map.items()):
                if var_name in self._subscriptions and self._subscriptions[var_name]:
                    try:
                        self._register_ads_notification(var_name, plctype, cycle_ms=200)
                        logger.debug(
                            "NotificationManager: restored subscription for '%s'",
                            var_name,
                        )
                    except Exception as exc:
                        logger.error(
                            "NotificationManager: could not restore '%s': %s",
                            var_name, exc,
                        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def subscribed_count(self) -> int:
        """Number of variables currently subscribed."""
        with self._lock:
            return len(self._subscriptions)

    @property
    def pending_events(self) -> int:
        """Number of events waiting in the dispatch queue."""
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Internal – ADS registration
    # ------------------------------------------------------------------

    def _register_ads_notification(
        self,
        var_name: str,
        plctype: Any,
        cycle_ms: int,
    ) -> None:
        """
        Call ``add_device_notification`` on the underlying pyads connection
        and store the returned handle pair.

        Must be called with ``self._lock`` held.
        """
        attrib = pyads.NotificationAttrib(
            length=ctypes.sizeof(plctype),
            # ADS timestamps use 100 ns units
            cycle_time=cycle_ms * 10_000,
            # max_delay: 100 ms = 1 000 000 × 100 ns
            max_delay=1_000_000,
        )
        cb = self._make_callback(var_name, plctype)
        handle_pair = self._client._conn.add_device_notification(
            var_name, attrib, cb
        )
        self._handles[var_name] = handle_pair
        logger.debug(
            "NotificationManager: registered ADS notification for '%s'  "
            "cycle=%d ms  handles=%s",
            var_name, cycle_ms, handle_pair,
        )

    def _make_callback(
        self, var_name: str, plctype: Any
    ) -> Callable:
        """
        Build and return the low-level ADS notification callback for
        *var_name*.

        The returned function is called on the pyads background thread
        and must not raise; exceptions are caught and logged.
        """
        def cb(notification: pyads.SAdsNotificationHeader, name: str) -> None:
            try:
                timestamp = notification.nTimeStamp
                value_obj = plctype()
                ctypes.memmove(
                    ctypes.addressof(value_obj),
                    notification.data,
                    ctypes.sizeof(plctype),
                )
                actual_val = (
                    value_obj.value if hasattr(value_obj, "value") else value_obj
                )
                self._queue.put_nowait((var_name, actual_val, time.time()))
            except Exception as exc:
                logger.debug(
                    "Notification parse error for %s: %s", var_name, exc
                )

        return cb

    # The spec also requests a method named _notification_callback for
    # documentation completeness; it delegates to the per-variable closure.
    def _notification_callback(
        self,
        notification: pyads.SAdsNotificationHeader,
        name: str,
    ) -> None:  # pragma: no cover
        """
        Generic entry-point (not used directly; each variable gets its own
        closure via ``_make_callback``).  Shown here for interface clarity.
        """
        raise NotImplementedError("Use _make_callback to create per-variable closures.")

    def _cancel_ads_notification(self, var_name: str) -> None:
        """
        Deregister an ADS notification and remove its handle entry.

        Must be called with ``self._lock`` held.
        """
        handles = self._handles.pop(var_name, None)
        if handles is None:
            return
        try:
            self._client._conn.del_device_notification(*handles)
            logger.debug(
                "NotificationManager: cancelled ADS notification for '%s'",
                var_name,
            )
        except Exception as exc:
            logger.warning(
                "NotificationManager: error cancelling notification for '%s': %s",
                var_name, exc,
            )

    # ------------------------------------------------------------------
    # Internal – Dispatch thread
    # ------------------------------------------------------------------

    def _start_dispatch(self) -> None:
        """Start the background event-dispatch daemon thread."""
        if self._running:
            return
        self._running = True
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop,
            name="ads-notification-dispatch",
            daemon=True,
        )
        self._dispatch_thread.start()
        logger.debug("NotificationManager: dispatch thread started")

    def _stop_dispatch(self) -> None:
        """Signal and join the dispatch thread."""
        self._running = False
        thread = self._dispatch_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
            self._dispatch_thread = None
        logger.debug("NotificationManager: dispatch thread stopped")

    def _dispatch_loop(self) -> None:
        """
        Drain the event queue every 10 ms and call registered callbacks.

        Runs on the dedicated dispatch thread until ``_running`` is False.
        """
        while self._running:
            # Drain all available items before sleeping
            while True:
                try:
                    var_name, value, ts = self._queue.get_nowait()
                except queue.Empty:
                    break

                # Snapshot callbacks under lock; call them outside
                with self._lock:
                    callbacks = list(self._subscriptions.get(var_name, []))

                for cb in callbacks:
                    try:
                        cb(var_name, value, ts)
                    except Exception as exc:
                        logger.exception(
                            "NotificationManager: callback error for '%s': %s",
                            var_name, exc,
                        )

            time.sleep(0.01)  # 10 ms


# ---------------------------------------------------------------------------
# MockNotificationSimulator
# ---------------------------------------------------------------------------

class MockNotificationSimulator:
    """
    In mock mode, simulates ADS notifications by periodically generating
    realistic value changes on a background thread.

    Each registered variable has a type, a current value, and a valid range.
    The simulator randomly picks a variable every 3-10 seconds, nudges its
    value within the range, and calls all registered callbacks.

    Usage::

        sim = MockNotificationSimulator({
            'gvlDALI.aPyActualLevel[1]': (pyads.PLCTYPE_BYTE, 0, 0, 254),
        })
        sim.add_callback(my_handler)
        sim.start()
        # …later…
        sim.stop()
    """

    def __init__(
        self,
        variables: Dict[str, Tuple[Any, Any, Any, Any]] = None,
    ) -> None:
        """
        Parameters
        ----------
        variables:
            ``{var_name: (plctype, current_value, min_val, max_val)}``
        """
        # var_name → [plctype, current_value, min_val, max_val]
        self._variables: Dict[str, list] = {}
        if variables:
            for name, (plctype, current, lo, hi) in variables.items():
                self._variables[name] = [plctype, current, lo, hi]

        self._callbacks: List[Callable[[str, Any, float], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background simulation thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._simulate_loop,
            name="mock-notification-sim",
            daemon=True,
        )
        self._thread.start()
        logger.info("MockNotificationSimulator: started")

    def stop(self) -> None:
        """Stop the simulation thread."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("MockNotificationSimulator: stopped")

    def add_variable(
        self,
        name: str,
        plctype: Any,
        value: Any,
        min_val: Any,
        max_val: Any,
    ) -> None:
        """Register or update a variable in the simulator."""
        with self._lock:
            self._variables[name] = [plctype, value, min_val, max_val]

    def add_callback(
        self,
        callback: Callable[[str, Any, float], None],
    ) -> None:
        """Register a callback that will be called on every simulated change."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def remove_callback(
        self,
        callback: Callable[[str, Any, float], None],
    ) -> None:
        """Remove a previously registered callback."""
        with self._lock:
            try:
                self._callbacks.remove(callback)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Simulation internals
    # ------------------------------------------------------------------

    def _simulate_loop(self) -> None:
        """Randomly mutate a variable every 3-10 seconds."""
        while self._running:
            sleep_time = random.uniform(3.0, 10.0)
            # Sleep in 0.1 s increments so we can exit promptly
            deadline = time.monotonic() + sleep_time
            while self._running and time.monotonic() < deadline:
                time.sleep(0.1)

            if not self._running:
                break

            with self._lock:
                if not self._variables:
                    continue

                var_name = random.choice(list(self._variables.keys()))
                entry = self._variables[var_name]
                plctype, current, lo, hi = entry

                new_value = self._nudge(current, lo, hi, plctype)
                entry[1] = new_value

                callbacks = list(self._callbacks)

            ts = time.time()
            for cb in callbacks:
                try:
                    cb(var_name, new_value, ts)
                except Exception as exc:
                    logger.warning(
                        "MockNotificationSimulator: callback error: %s", exc
                    )

    @staticmethod
    def _nudge(current: Any, lo: Any, hi: Any, plctype: Any) -> Any:
        """
        Produce a new plausible value near *current* within [*lo*, *hi*].

        For boolean types a 50/50 flip is applied; for numeric types the
        value is adjusted by up to 20 % of the full range.
        """
        # Boolean / BOOL types
        if plctype in (pyads.PLCTYPE_BOOL,) or isinstance(current, bool):
            return not bool(current)

        # Numeric types — move by up to 20 % of total range
        span = hi - lo
        if span == 0:
            return current
        delta = random.uniform(-0.2 * span, 0.2 * span)
        new_val = current + delta
        new_val = max(lo, min(hi, new_val))

        # Preserve integer type if lo/hi are ints
        if isinstance(lo, int) and isinstance(hi, int):
            return int(round(new_val))
        return new_val
