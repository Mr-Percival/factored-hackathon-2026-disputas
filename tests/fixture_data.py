"""Compatibilidad: el fixture vive en `bankagent.demo_fixture` (lo usa también la demo web)."""
from bankagent.demo_fixture import (  # noqa: F401
    CANARY_MERCHANT,
    COMPLAINTS,
    CUSTOMERS,
    MALICIOUS_MERCHANT,
    PRODUCTS,
    TXNS,
    _txn,
    _w,
    write_fixture,
    write_late_batch,
)
