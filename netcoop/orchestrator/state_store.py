"""NetCoop AI Orchestrator - State Store and Pipeline Checkpointing.

Persists JSON checkpoints per incident under logs/state_<incident>.json across
pipeline stages ('ingested', 'analysed', 'correlated', 'reported') to support crash resilience
and stage resumption.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union


class StateStore:
    """Manages disk-backed checkpointing and resumption of incident diagnoses."""

    def __init__(self, log_dir: Union[str, Path] = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def checkpoint(
        self,
        incident_id: str,
        stage: str,
        state_data: Dict[str, Any],
    ) -> Path:
        """Write or update an incident stage checkpoint file."""
        state_file = self.log_dir / f"state_{incident_id}.json"

        data: Dict[str, Any] = {}
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data["incident_id"] = incident_id
        data["last_stage"] = stage
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        data[stage] = state_data

        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return state_file

    def load(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Load checkpoint state from disk if available."""
        state_file = self.log_dir / f"state_{incident_id}.json"
        if not state_file.exists():
            return None
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def resume(self, incident_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the latest checkpointed state for resumption."""
        return self.load(incident_id)