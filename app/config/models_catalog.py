"""
Loader for models_catalog.yaml — the canonical list of known provider models.

Usage:
    from app.config.models_catalog import load_models_catalog
    catalog = load_models_catalog()
    # catalog["llm"]["openai"]["models"]  -> list of {id, display_name, notes}
"""
from functools import lru_cache
from pathlib import Path
import yaml

_CATALOG_PATH = Path(__file__).parent.parent.parent / "models_catalog.yaml"


@lru_cache(maxsize=1)
def load_models_catalog() -> dict:
    """
    Load and return the models catalog as a plain dict.
    Cached for the process lifetime (same pattern as load_config).
    """
    if not _CATALOG_PATH.exists():
        raise FileNotFoundError(
            f"models_catalog.yaml not found at {_CATALOG_PATH}."
        )
    with _CATALOG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_models_for_role_and_provider(role: str, provider: str) -> list:
    """
    Returns the list of model dicts for a given role ('embedding' or 'llm')
    and provider ('ollama', 'openai', etc.).
    Returns an empty list if the combination is not in the catalog.
    """
    catalog = load_models_catalog()
    return catalog.get(role, {}).get(provider, {}).get("models", [])
