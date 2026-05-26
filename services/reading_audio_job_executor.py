import sys as _sys

from services.reading import audio_job_executor as _audio_job_executor
from services.reading.audio_job_executor import *  # noqa: F401,F403

_sys.modules[__name__] = _audio_job_executor
