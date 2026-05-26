import sys as _sys

from services.reading import audio_queue as _audio_queue
from services.reading.audio_queue import *  # noqa: F401,F403

_sys.modules[__name__] = _audio_queue
