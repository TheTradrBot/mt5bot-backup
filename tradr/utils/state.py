"""
State management utilities for persisting bot state.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class StateManager:
    """
    Generic state manager for persisting data to JSON.
    """
    
    def __init__(self, state_file: str = "bot_state.json"):
        self.state_file = Path(state_file)
        self._state: Dict[str, Any] = {}
        self._load()
    
    def _load(self):
        """Load state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    self._state = json.load(f)
            except Exception as e:
                print(f"[StateManager] Error loading state: {e}")
                self._state = {}
        else:
            self._state = {}
    
    def save(self):
        """Save state to file."""
        try:
            self._state["_last_updated"] = datetime.now(timezone.utc).isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self._state, f, indent=2, default=str)
        except Exception as e:
            print(f"[StateManager] Error saving state: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from state."""
        return self._state.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set a value in state and save."""
        self._state[key] = value
        self.save()
    
    def delete(self, key: str):
        """Delete a key from state and save."""
        if key in self._state:
            del self._state[key]
            self.save()
    
    def clear(self):
        """Clear all state."""
        self._state = {}
        self.save()
    
    def all(self) -> Dict[str, Any]:
        """Get all state."""
        return self._state.copy()
