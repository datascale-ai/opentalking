"""Transport-neutral realtime program output primitives.

The streaming package deliberately does not know about a model, a Session
runner, or a third-party control plane.  Runners publish normalised audio and
video into :class:`ProgramOutputManager`; protocol publishers consume an
independent branch queue.
"""

from .clock import ProgramClock
from .manager import ProgramOutputManager
from .types import OutputBranchStats, ProgramAudio, ProgramVideo

__all__ = [
    "OutputBranchStats",
    "ProgramAudio",
    "ProgramClock",
    "ProgramOutputManager",
    "ProgramVideo",
]
