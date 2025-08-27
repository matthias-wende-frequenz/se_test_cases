from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from frequenz.quantities import Percentage, Power


@dataclass(frozen=True, kw_only=True)
class Config:
    """Actor configuration."""

    min_soc: Percentage = field(default_factory=lambda: Percentage.from_fraction(0.1))
    target_power: Power = field(default_factory=lambda: Power.from_kilowatts(25))

    @classmethod
    def create(cls, config: dict[str, Any]) -> Config:
        """Create a new Config object from a dictionary."""
        return cls(
            target_power=Power.from_watts(config["truck_charging"]["target_power_w"]),
            min_soc=Percentage.from_fraction(config["truck_charging"]["min_soc"]),
        )
