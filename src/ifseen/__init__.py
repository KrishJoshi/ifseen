"""ifseen - if seen (or heard), then do.

Library use::

    from ifseen import Watcher, check, FireEvent
"""

from .actions import FireEvent
from .config import ConfigError, WatchConfig
from .constants import VERSION as __version__
from .oneshot import CheckResult, check, check_detailed
from .providers import Provider, ProviderConfigError, ProviderError
from .sources import SourceError
from .watcher import Watcher

__all__ = [
    "CheckResult",
    "ConfigError",
    "FireEvent",
    "Provider",
    "ProviderConfigError",
    "ProviderError",
    "SourceError",
    "WatchConfig",
    "Watcher",
    "__version__",
    "check",
    "check_detailed",
]
