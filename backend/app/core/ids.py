"""Identificadores UUIDv7 (RFC 9562) monotónicos dentro del proceso.

Python 3.12 no incluye ``uuid.uuid7``. Esta implementación usa el método 1 del RFC
(contador de 12 bits en ``rand_a``) para garantizar orden estricto aunque se generen
varios IDs en el mismo milisegundo.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0
_COUNTER_MAX = 0xFFF


def uuid7() -> uuid.UUID:
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms = ms
            _counter = secrets.randbits(11)  # deja margen para incrementar
        else:
            _counter += 1
            if _counter > _COUNTER_MAX:
                _last_ms += 1
                _counter = 0
        ms_value = _last_ms
        counter = _counter
    rand_b = secrets.randbits(62)
    value = (
        ((ms_value & 0xFFFF_FFFF_FFFF) << 80)
        | (0x7 << 76)
        | (counter << 64)
        | (0b10 << 62)
        | rand_b
    )
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    """Devuelve el instante (ms Unix) codificado en un UUIDv7."""
    return value.int >> 80
