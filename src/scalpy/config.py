from pathlib import Path

from dynaconf import Dynaconf

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

settings = Dynaconf(
    settings_files=[
        str(_PROJECT_ROOT / "config" / "settings.toml"),
        str(_PROJECT_ROOT / "config" / ".secrets.toml"),
    ],
    environments=True,
    env_prefix="SCALPY",
)
