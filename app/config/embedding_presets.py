"""
Loader for embedding_presets.yaml.
"""
from functools import lru_cache
from pathlib import Path
import yaml

_PRESETS_PATH = Path(__file__).parent.parent.parent / "embedding_presets.yaml"


@lru_cache(maxsize=1)
def load_embedding_presets() -> dict:
    if not _PRESETS_PATH.exists():
        raise FileNotFoundError(f"embedding_presets.yaml not found at {_PRESETS_PATH}.")
    with _PRESETS_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    data.setdefault("presets", {})
    return data
