"""NetCoop AI Configuration Loader.

Merges thresholds, scoring, and agent-specific configurations.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union
import yaml


def get_config_dir(custom_path: Optional[Union[str, Path]] = None) -> Path:
    """Resolve project configuration directory."""
    if custom_path:
        p = Path(custom_path)
        if p.exists() and p.is_dir():
            return p
    cwd_cfg = Path("config")
    if cwd_cfg.exists() and cwd_cfg.is_dir():
        return cwd_cfg
    pkg_cfg = Path(__file__).resolve().parent.parent / "config"
    if pkg_cfg.exists() and pkg_cfg.is_dir():
        return pkg_cfg
    return cwd_cfg


def load_config(config_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Load and merge thresholds.yaml, scoring.yaml, and config/agents/*.yaml.

    Returns:
        dict: {"thresholds": ..., "scoring": ..., "agents": {name: {...}}}
    """
    base_dir = get_config_dir(config_dir)

    thresholds_file = base_dir / "thresholds.yaml"
    scoring_file = base_dir / "scoring.yaml"
    agents_dir = base_dir / "agents"

    thresholds: Dict[str, Any] = {}
    if thresholds_file.exists():
        with open(thresholds_file, "r", encoding="utf-8") as f:
            thresholds = yaml.safe_load(f) or {}

    scoring: Dict[str, Any] = {}
    if scoring_file.exists():
        with open(scoring_file, "r", encoding="utf-8") as f:
            scoring = yaml.safe_load(f) or {}

    agents: Dict[str, Any] = {}
    if agents_dir.exists() and agents_dir.is_dir():
        for agent_file in sorted(agents_dir.glob("*.yaml")):
            agent_name = agent_file.stem
            with open(agent_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
                agents[agent_name] = cfg if isinstance(cfg, dict) else {}

    return {
        "thresholds": thresholds,
        "scoring": scoring,
        "agents": agents,
    }


def agent_config(name: str, config_dir: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Return configuration dictionary for a specific agent."""
    cfg = load_config(config_dir)
    return cfg.get("agents", {}).get(name, {})