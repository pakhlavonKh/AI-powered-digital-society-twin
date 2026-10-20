"""Scenario loading, parsing, and serialization functions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union

import yaml
from pydantic import ValidationError

try:
    from .schema import ScenarioConfig
except ImportError:
    from scenarios.schema import ScenarioConfig  # type: ignore


class ScenarioError(Exception):
    """Base exception for scenario engine errors."""
    pass


class ScenarioNotFoundError(ScenarioError, FileNotFoundError):
    """Raised when a scenario configuration file cannot be found."""
    pass


class ScenarioParseError(ScenarioError, ValueError):
    """Raised when scenario text contains invalid YAML or JSON syntax."""
    pass


class ScenarioValidationError(ScenarioError, ValueError):
    """Raised when a scenario violates structural or validation constraints."""
    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


def load_scenario(source: Union[str, Path, dict[str, Any]]) -> ScenarioConfig:
    """Load and validate a scenario from a YAML file, JSON file, or raw dictionary.

    Args:
        source: Filepath (str or Path) or a Python dictionary representing the scenario.

    Returns:
        ScenarioConfig: Fully validated scenario instance.

    Raises:
        ScenarioNotFoundError: If the specified file does not exist.
        ScenarioParseError: If file content cannot be parsed as valid YAML or JSON.
        ScenarioValidationError: If configuration fails validation rules.
    """
    raw_data: Any

    if isinstance(source, dict):
        raw_data = source
    else:
        path = Path(source).resolve()
        if not path.is_file():
            raise ScenarioNotFoundError(f"Scenario configuration file not found at: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise ScenarioError(f"Failed to read scenario file at '{path}': {exc}") from exc

        try:
            if path.suffix.lower() == ".json":
                raw_data = json.loads(content)
            else:
                raw_data = yaml.safe_load(content)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            raise ScenarioParseError(f"Syntax error while parsing scenario file '{path}': {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ScenarioValidationError(
            f"Scenario data must be a dictionary/mapping, but got {type(raw_data).__name__}"
        )

    try:
        return ScenarioConfig.model_validate(raw_data)
    except ValidationError as exc:
        details: list[dict[str, Any]] = []
        messages: list[str] = []
        for err in exc.errors():
            loc = " -> ".join(str(elem) for elem in err["loc"])
            msg = err["msg"]
            details.append({"location": loc, "message": msg, "type": err["type"]})
            messages.append(f"Field '{loc}': {msg}")

        full_message = f"Scenario validation failed with {len(messages)} error(s):\n  - " + "\n  - ".join(messages)
        raise ScenarioValidationError(full_message, errors=details) from exc


def save_scenario(scenario: ScenarioConfig, path: Union[str, Path], file_format: str = "yaml") -> None:
    """Serialize a ScenarioConfig to a YAML or JSON file.

    Args:
        scenario: Validated ScenarioConfig instance.
        path: Target file path.
        file_format: 'yaml' or 'json' (defaults to 'yaml').
    """
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = scenario.model_dump(exclude_none=True)

    if file_format.lower() == "json":
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        # Default PyYAML dump with nice block styling
        target.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
