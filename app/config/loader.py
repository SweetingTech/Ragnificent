import yaml
import os
from .schema import GlobalConfig

def load_config(config_path: str = "config.yaml") -> GlobalConfig:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at {config_path}")
    
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    
    return GlobalConfig(**data)
