from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import PlatformDirs


@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    log_dir: Path

    @classmethod
    def discover(cls) -> AppPaths:
        dirs = PlatformDirs(appname="susanoox", appauthor="Susanoox", roaming=True)
        return cls(
            config_dir=Path(dirs.user_config_dir),
            data_dir=Path(dirs.user_data_dir),
            cache_dir=Path(dirs.user_cache_dir),
            log_dir=Path(dirs.user_log_dir),
        )
