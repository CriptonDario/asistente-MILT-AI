"""Reloj lógico híbrido (HLC) para ordenar cambios entre dispositivos (sincronización)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class HLCTimestamp:
    physical_ms: int
    counter: int
    node: str

    def __str__(self) -> str:
        return f"{self.physical_ms:013d}:{self.counter:05d}:{self.node}"

    @classmethod
    def parse(cls, raw: str) -> HLCTimestamp:
        try:
            physical, counter, node = raw.split(":", 2)
            return cls(int(physical), int(counter), node)
        except ValueError as exc:
            raise ValueError(f"marca HLC no válida: {raw!r}") from exc


class HybridLogicalClock:
    """HLC: combina el reloj físico con un contador para tolerar relojes desajustados."""

    def __init__(self, node: str) -> None:
        if not node or ":" in node:
            raise ValueError("el identificador de nodo no puede estar vacío ni contener ':'")
        self._node = node
        self._last_ms = 0
        self._counter = 0
        self._lock = threading.Lock()

    @property
    def node(self) -> str:
        return self._node

    def now(self) -> str:
        with self._lock:
            physical = time.time_ns() // 1_000_000
            if physical > self._last_ms:
                self._last_ms = physical
                self._counter = 0
            else:
                self._counter += 1
            return str(HLCTimestamp(self._last_ms, self._counter, self._node))

    def update(self, remote: str) -> str:
        """Avanza el reloj tras recibir una marca remota (usado por la sincronización)."""
        other = HLCTimestamp.parse(remote)
        with self._lock:
            physical = time.time_ns() // 1_000_000
            new_ms = max(physical, self._last_ms, other.physical_ms)
            if new_ms == self._last_ms == other.physical_ms:
                self._counter = max(self._counter, other.counter) + 1
            elif new_ms == self._last_ms:
                self._counter += 1
            elif new_ms == other.physical_ms:
                self._counter = other.counter + 1
            else:
                self._counter = 0
            self._last_ms = new_ms
            return str(HLCTimestamp(self._last_ms, self._counter, self._node))
