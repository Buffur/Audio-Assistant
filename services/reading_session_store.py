import sys as _sys

from services.reading.infrastructure import session_store as _session_store
from services.reading.infrastructure.session_store import *  # noqa: F401,F403

_sys.modules[__name__] = _session_store
