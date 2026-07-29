"""Configuration-driven team compositions for live policy episodes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPTED_BEHAVIORS = ("skirmisher", "guardian", "striker")


@dataclass(frozen=True)
class TeamComposition:
    name: str
    learned_count: int
    scripted_behaviors: tuple[str, ...]

    @property
    def kind(self) -> str:
        if self.learned_count == 1 and not self.scripted_behaviors:
            return "solo"
        if self.learned_count == 1:
            return "mixed"
        return "multi-learned"

    @property
    def participant_count(self) -> int:
        return self.learned_count + len(self.scripted_behaviors)

    def to_log(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "learned_count": self.learned_count,
            "scripted_behaviors": list(self.scripted_behaviors),
            "bot_count": self.participant_count,
        }


def _composition(value: object, index: int) -> TeamComposition:
    if not isinstance(value, Mapping):
        raise ValueError(f"composition {index} must be an object")
    name = value.get("name")
    learned_count = value.get("learned_count")
    scripted = value.get("scripted_behaviors", [])
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"composition {index} has an invalid name")
    if (
        isinstance(learned_count, bool)
        or not isinstance(learned_count, int)
        or learned_count < 1
    ):
        raise ValueError(
            f"composition {name!r} learned_count must be positive"
        )
    if not isinstance(scripted, list) or not all(
        isinstance(item, str) and item in SCRIPTED_BEHAVIORS
        for item in scripted
    ):
        raise ValueError(
            f"composition {name!r} has an invalid scripted behavior"
        )
    if learned_count > 1 and scripted:
        raise ValueError(
            f"composition {name!r} cannot mix multiple learned and "
            "scripted participants"
        )
    return TeamComposition(
        name=name.strip(),
        learned_count=learned_count,
        scripted_behaviors=tuple(scripted),
    )


def load_compositions(path: Path) -> tuple[TeamComposition, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError("composition config must be an object")
    if document.get("schema_version") != 1:
        raise ValueError("composition config schema_version must be 1")
    values = document.get("compositions")
    if not isinstance(values, list) or not values:
        raise ValueError("composition config must contain compositions")
    result = tuple(
        _composition(value, index)
        for index, value in enumerate(values, start=1)
    )
    names = [item.name for item in result]
    if len(set(names)) != len(names):
        raise ValueError("composition names must be unique")
    if not any(item.kind == "solo" for item in result):
        raise ValueError("composition config must include a solo episode")
    if not any(item.kind == "mixed" for item in result):
        raise ValueError("composition config must include a mixed episode")
    if not any(item.kind == "multi-learned" for item in result):
        raise ValueError(
            "composition config must include a multi-learned episode"
        )
    return result


def select_compositions(
    compositions: Sequence[TeamComposition],
    requested_names: Iterable[str],
) -> tuple[TeamComposition, ...]:
    names = tuple(requested_names)
    if not names:
        return tuple(compositions)
    by_name = {item.name: item for item in compositions}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise ValueError(
            "unknown composition name(s): " + ", ".join(missing)
        )
    return tuple(by_name[name] for name in names)


def build_roster(
    composition: TeamComposition,
    *,
    element: str,
    discipline: str,
) -> list[dict[str, str]]:
    roster = [
        {
            "name": f"Learner {index}",
            "element": element,
            "behavior": "learned",
            "discipline": discipline,
        }
        for index in range(1, composition.learned_count + 1)
    ]
    scripted_elements = ("water", "earth", "air", "ether", "fire")
    for index, behavior in enumerate(
        composition.scripted_behaviors,
        start=1,
    ):
        roster.append(
            {
                "name": f"{behavior.title()} {index}",
                "element": scripted_elements[(index - 1) % len(scripted_elements)],
                "behavior": behavior,
                "discipline": discipline,
            }
        )
    return roster
