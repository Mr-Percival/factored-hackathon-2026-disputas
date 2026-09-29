"""Compatibilidad: el fixture vive en `bankagent.demo_fixture` (lo usa también la demo web)."""
from bankagent.demo_fixture import (CANARY_MERCHANT, MALICIOUS_MERCHANT, write_fixture,  # noqa: F401
                                    write_late_batch)
