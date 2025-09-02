"""Configuration for the PowerCurtailmentActor."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from marshmallow import ValidationError, fields


class TimedeltaField(fields.Field):
    """Custom marshmallow field for parsing timedelta from numeric seconds."""

    def _serialize(
        self, value: timedelta | None, attr: str | None, obj: Any, **kwargs: Any
    ) -> int | None:
        """Serialize timedelta to total seconds."""
        if value is None:
            return None
        return int(value.total_seconds())

    def _deserialize(
        self, value: Any, attr: str | None, data: Any, **kwargs: Any
    ) -> timedelta | None:
        """Deserialize numeric seconds to timedelta."""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return timedelta(seconds=value)

        raise ValidationError("Timedelta must be a number representing seconds.")


@dataclass(frozen=True)
class PowerCurtailmentConfig:
    """Configuration for the PowerCurtailmentActor."""

    run_frequency: timedelta = field(metadata={"marshmallow_field": TimedeltaField()})
    """Interval between runs of the actor."""

    da_price_frequency: str
    """Frequency string (e.g., '15min', '1H') specifying the frequency of the day ahead prices."""

    microgrid_ids: list[int]
    """Ids of the microgrids for which to curtail charging."""

    price_limit: float
    """Price limit above which power curtailment dispatch should be sent."""

    retries: int = 3
    """Number of retries if fetching day ahead prices fails."""

    initial_backoff: timedelta = field(
        default=timedelta(minutes=1), metadata={"marshmallow_field": TimedeltaField()}
    )
    """Initial delay before the first retry. Doubles with each subsequent retry."""

    country_code: str = "DE_LU"
    """Country for which to query the day ahead prices."""

    power_reduction_w: float = 0.0
    """Power reduction in watts to apply during power curtailment. Default is 0.0 (no curtailment)."""

    def __post_init__(self) -> None:
        """Check that the retry does not extend into the next run.

        Raises:
            ValueError: If the retry window exceeds the run frequency.
        """
        retry_window = self.initial_backoff * (2**self.retries - 1)
        if retry_window >= self.run_frequency:
            raise ValueError(
                f"Invalid schedule:"
                f"{self.retries} retries with initial backoff "
                f"{self.initial_backoff} result in total delay exceeding the run frequency "
                f"{self.run_frequency}."
            )
