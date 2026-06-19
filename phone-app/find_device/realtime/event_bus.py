"""
Internal publish/subscribe event bus for distributing PLC variable changes
to SSE (Server-Sent Events) clients.

Architecture
------------
* PLC variable changes are published here by the notification layer.
* Each connected SSE client registers a ``queue.Queue`` via
  ``register_client()``.
* The view's SSE generator drains its queue and streams events to the browser.
* ``EventBus`` is a process-wide singleton — obtain it via
  ``EventBus.instance()``.

Thread safety
-------------
All public methods are protected by ``self._lock`` (a re-entrant lock) so
they are safe to call from any thread (Django request threads, ADS
notification threads, heartbeat timers, etc.).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Maximum events buffered per client before the oldest are dropped.
_MAX_QUEUE_SIZE = 500


class EventBus:
    """
    Singleton publish/subscribe event bus.

    All ``publish_*`` methods are non-blocking: they iterate over every
    registered client queue and call ``put_nowait()``.  If a client queue
    has grown beyond ``_MAX_QUEUE_SIZE`` items the oldest event is discarded
    to make room, preventing unbounded memory growth for slow or stalled
    clients.

    Example::

        bus = EventBus.instance()

        # SSE view — called once per client connection
        q = bus.register_client(client_id)
        try:
            while True:
                event = q.get(timeout=20)
                yield f"data: {json.dumps(event)}\\n\\n"
        finally:
            bus.unregister_client(client_id)

        # ADS notification callback — called from background thread
        bus.publish(device_id=1, var_name='gvlDALI.aPyActualLevel[1]', value=128)
    """

    _instance: Optional["EventBus"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        # client_id → event queue
        self._client_queues: Dict[str, queue.Queue] = {}
        self._lock: threading.RLock = threading.RLock()
        self._event_count: int = 0

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "EventBus":
        """Return the process-wide singleton, creating it if necessary."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
                    logger.debug("EventBus: singleton created")
        return cls._instance

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(
        self,
        device_id: int,
        var_name: str,
        value: Any,
        timestamp: float = None,
    ) -> None:
        """
        Publish a variable-change event to all registered SSE clients.

        Parameters
        ----------
        device_id:
            Numeric device / channel identifier.
        var_name:
            Fully-qualified PLC variable name.
        value:
            New variable value (must be JSON-serialisable).
        timestamp:
            Unix timestamp of the change.  Defaults to ``time.time()``.
        """
        with self._lock:
            self._event_count += 1
            event = {
                "type": "variable_change",
                "device_id": device_id,
                "var_name": var_name,
                "value": value,
                "timestamp": timestamp if timestamp is not None else time.time(),
                "seq": self._event_count,
            }
            self._broadcast(event)

    def publish_connection(
        self,
        device_id: int,
        connected: bool,
        ads_state: str = "UNKNOWN",
    ) -> None:
        """
        Publish a connection-state-change event.

        Parameters
        ----------
        device_id:
            Numeric device / PLC identifier.
        connected:
            ``True`` if the PLC just came online, ``False`` if it dropped.
        ads_state:
            Human-readable ADS state string (e.g. ``'RUN'``, ``'STOP'``).
        """
        with self._lock:
            self._event_count += 1
            event = {
                "type": "connection_change",
                "device_id": device_id,
                "connected": connected,
                "ads_state": ads_state,
                "timestamp": time.time(),
                "seq": self._event_count,
            }
            self._broadcast(event)

    def publish_alarm(
        self,
        device_id: int,
        var_name: str,
        active: bool,
        label: str = "",
    ) -> None:
        """
        Publish an alarm-state event.

        Parameters
        ----------
        device_id:
            Numeric device identifier.
        var_name:
            PLC variable that triggered the alarm.
        active:
            ``True`` when the alarm condition is active (onset), ``False``
            when it has cleared.
        label:
            Human-readable alarm description.
        """
        with self._lock:
            self._event_count += 1
            event = {
                "type": "alarm",
                "device_id": device_id,
                "var_name": var_name,
                "active": active,
                "label": label,
                "timestamp": time.time(),
                "seq": self._event_count,
            }
            self._broadcast(event)

    def heartbeat(self) -> None:
        """
        Broadcast a heartbeat event to all clients.

        Call this on a regular interval (e.g. every 15 s) so SSE clients
        can detect connection loss if no real events are flowing.  The
        heartbeat does *not* increment the ``total_events_published`` counter
        because it carries no data.
        """
        event = {
            "type": "heartbeat",
            "ts": time.time(),
        }
        with self._lock:
            self._broadcast(event, count=False)

    # ------------------------------------------------------------------
    # Client registration
    # ------------------------------------------------------------------

    def register_client(self, client_id: str) -> queue.Queue:
        """
        Register an SSE client and return its dedicated event queue.

        If *client_id* was previously registered the existing queue is
        returned (idempotent).

        Parameters
        ----------
        client_id:
            Unique identifier for the client connection.  Pass
            ``str(uuid.uuid4())`` if you don't already have one.

        Returns
        -------
        queue.Queue
            The queue the caller should drain to read events.
        """
        with self._lock:
            if client_id not in self._client_queues:
                self._client_queues[client_id] = queue.Queue()
                logger.debug(
                    "EventBus: registered client '%s'  total=%d",
                    client_id, len(self._client_queues),
                )
            return self._client_queues[client_id]

    def unregister_client(self, client_id: str) -> None:
        """
        Remove a client and discard its event queue.

        Safe to call even if the client was never registered.
        """
        with self._lock:
            if client_id in self._client_queues:
                del self._client_queues[client_id]
                logger.debug(
                    "EventBus: unregistered client '%s'  total=%d",
                    client_id, len(self._client_queues),
                )

    def get_queue(self, client_id: str) -> Optional[queue.Queue]:
        """
        Return the queue for *client_id*, or ``None`` if not registered.
        """
        with self._lock:
            return self._client_queues.get(client_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """Number of currently registered SSE clients."""
        with self._lock:
            return len(self._client_queues)

    @property
    def total_events_published(self) -> int:
        """
        Cumulative number of data events published since the bus was created.

        Heartbeats are excluded from this count.
        """
        with self._lock:
            return self._event_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _broadcast(self, event: dict, count: bool = True) -> None:
        """
        Put *event* into every registered client queue.

        If a queue has reached ``_MAX_QUEUE_SIZE``, the oldest item is
        discarded before inserting the new one so the queue never grows
        without bound.

        Must be called with ``self._lock`` held.

        Parameters
        ----------
        event:
            The event dict to broadcast.
        count:
            Whether this event has already been counted in ``_event_count``
            (heartbeats pass ``False``).
        """
        for client_id, q in self._client_queues.items():
            # Drop oldest event if the queue is full
            if q.qsize() >= _MAX_QUEUE_SIZE:
                try:
                    q.get_nowait()
                    logger.warning(
                        "EventBus: dropped oldest event for slow client '%s'",
                        client_id,
                    )
                except queue.Empty:
                    pass

            try:
                q.put_nowait(event)
            except queue.Full:
                # put_nowait on an unbounded Queue never raises Full, but
                # guard defensively in case someone passes a bounded queue.
                logger.warning(
                    "EventBus: queue full for client '%s', event dropped",
                    client_id,
                )
