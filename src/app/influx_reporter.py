import logging
import os

from frequenz.quantities import Percentage, Power
from influxdb_client_3 import (
    InfluxDBClient3,
    InfluxDBError,
    Point,
    WriteOptions,
    write_client_options,
)

_logger = logging.getLogger(__name__)

# --- InfluxDB Configuration ---
INFLUX_HOST = os.getenv("INFLUX_HOST", "http://localhost:8181")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_DATABASE = os.getenv("INFLUX_DATABASE", "electrical_monitoring")


def success_callback(self, data: str):
    """Callback for successful InfluxDB write."""
    _logger.info(f"Successfully wrote batch to InfluxDB: {data}")


def error_callback(self, data: str, exception: InfluxDBError):
    """Callback for failed InfluxDB write."""
    _logger.error(f"Failed writing batch to InfluxDB: {data} due to: {exception}")


def retry_callback(self, data: str, exception: InfluxDBError):
    """Callback for retried InfluxDB write."""
    _logger.warning(f"Retrying batch to InfluxDB: {data} after error: {exception}")


class InfluxReporter:
    """A class to handle reporting metrics to InfluxDB."""

    def __init__(self):
        """Initialize the InfluxReporter and the InfluxDB client."""
        # Configure options for batch writing to InfluxDB.
        write_options = WriteOptions(
            batch_size=500,
            flush_interval=10_000,
            jitter_interval=2_000,
            retry_interval=5_000,
            max_retries=5,
            max_retry_delay=30_000,
            exponential_base=2,
        )

        # Create an options dict that sets callbacks and WriteOptions.
        wco = write_client_options(
            success_callback=success_callback,
            error_callback=error_callback,
            retry_callback=retry_callback,
            write_options=write_options,
        )

        # Instantiate the InfluxDB client.
        self._influx_client = InfluxDBClient3(
            host=INFLUX_HOST,
            token=INFLUX_TOKEN,
            database=INFLUX_DATABASE,
            write_client_options=wco,
        )
        _logger.info(
            f"InfluxReporter initialized. Writing metrics to InfluxDB database '{INFLUX_DATABASE}'."
        )

    def report_metrics(
        self,
        latest_grid_power: Power | None,
        latest_prod_power: Power | None,
        latest_battery_power: Power | None,
        latest_battery_soc: Percentage | None,
    ):
        """
        Create a data point and write it to InfluxDB.

        Args:
            latest_grid_power: The latest grid power measurement.
            latest_prod_power: The latest production power measurement.
            latest_battery_power: The latest battery power measurement.
            latest_battery_soc: The latest battery state of charge measurement.
        """
        try:
            point = Point("power_metrics").tag("actor", "TruckChargingActor")

            # Add fields only if they have a non-None value
            if latest_grid_power is not None:
                point.field("grid_power_watts", latest_grid_power.as_watts())
            if latest_prod_power is not None:
                point.field("production_power_watts", latest_prod_power.as_watts())
            if latest_battery_power is not None:
                point.field("battery_power_watts", latest_battery_power.as_watts())
            if latest_battery_soc is not None:
                point.field("battery_soc_percent", latest_battery_soc.as_percent())

            # Write the point to the InfluxDB client's buffer.
            # The client will batch and send it asynchronously.
            if point._fields:  # Only write if there are fields
                self._influx_client.write(point)
        except Exception as e:
            _logger.error(f"Failed to write metrics to InfluxDB: {e}")

    def close(self):
        """Close the InfluxDB client."""
        self._influx_client.close()
