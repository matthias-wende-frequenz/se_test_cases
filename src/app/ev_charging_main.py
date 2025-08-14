import asyncio
import logging
import os
import pathlib
from datetime import timedelta

from frequenz.channels import select, selected_from
from frequenz.quantities import Percentage, Power
from frequenz.sdk import microgrid
from frequenz.sdk.actor import Actor, ResamplerConfig, run
from frequenz.sdk.timeseries.battery_pool import BatteryPool
from frequenz.sdk.timeseries.ev_charger_pool import EVChargerPool

# Import the new InfluxReporter class
from .influx_reporter import InfluxReporter

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
_logger = logging.getLogger(__name__)


# Define path to the configuration file
CONFIG_PATH = pathlib.Path("config.toml")

# Define the TARGET_POWER constant (should be defined in the config or come from a dispatch event)
TARGET_POWER = 25000.0  # Default target power in watts

# Define the minimum state of charge for the battery
MIN_SOC = 0.1  # Minimum state of charge for the battery

# Define the microgrid API URL
MICROGRID_API_URL = "grpc://[::1]:8800"
# MICROGRID_API_URL = "grpc://microgrid.sandbox.api.frequenz.io:62060"

_logger = logging.getLogger(__name__)


class TcControlLogic:
    """Control Logic for the Truck Charging Actor"""

    def __init__(
        self,
        battery_pool: BatteryPool,
        ev_charger_pool: EVChargerPool,
        target_power: Power,
        min_soc: Percentage,
    ):
        """Initialize the control logic.
        Args:
            battery_pool: The battery pool to control.
            ev_charger_pool: The EV charger pool to control.
            target_power: The target power level for the grid.
            min_soc: The minimum state of charge for the battery.
        """
        self._battery_pool = battery_pool
        self._ev_charger_pool = ev_charger_pool
        self._target_power = target_power
        self._min_soc = min_soc

    async def run(
        self,
        latest_grid_power: Power,
        latest_battery_power: Power | None,
        latest_battery_soc: Percentage,
    ):
        """The main truck charging control logic.

        This method is supposed to be run whenever we receive a new measurement from a meter
        placed at the PCC.
        """
        # --- Flowchart Logic Implementation ---
        if latest_grid_power > self._target_power:
            if (
                latest_battery_soc > self._min_soc
                and latest_battery_soc is not None
                and latest_battery_power is not None
            ):
                residual_power = (
                    latest_grid_power + latest_battery_power
                ) - self._target_power
                # Discharge Battery & Restrict EV
                _logger.info("Discharging battery, restricting EVs.")
                # TODO use power_status's adjust_to_bounds method to calculate
                #      residual power after battery discharge
                await self._battery_pool.propose_power(residual_power)
                # await ev_charger_pool.set_power_bounds(0.0, residual_power)
            else:
                # Restrict EV Power only
                residual_power = latest_grid_power - self._target_power
                _logger.info("Restricting EV power.")
                # await ev_charger_pool.propose_power(residual_power)
        else:
            if latest_grid_power < Power.zero():  # Excess power is exported
                # Charge Battery with excess power only
                _logger.info("Charging battery with excess power.")
                if latest_battery_power is None:  # or latest_ev_power is None:
                    return

                charging_power = (
                    latest_grid_power + latest_battery_power
                )  # + latest_ev_power
                await self._battery_pool.propose_power(charging_power)
            else:
                _logger.debug("No control action needed.")


class TruckChargingActor(Actor):
    """Actor that implements the control logic for the EV charging system."""

    def __init__(self):
        """Initialize the TruckChargingActor."""
        super().__init__()
        # Instantiate the InfluxReporter
        self._influx_reporter = InfluxReporter()
        _logger.info("TruckChargingActor initialized.")

    async def _run(self) -> None:
        """Run the main actor logic."""
        # Get the high-level pools from the microgrid
        battery_pool = microgrid.new_battery_pool(priority=1)
        ev_charger_pool = microgrid.new_ev_charger_pool(priority=1)

        # get the data receivers for the relevant channels
        production_power = microgrid.producer().power
        battery_power = battery_pool.power
        battery_soc = battery_pool.soc
        ev_charger_power = ev_charger_pool.power
        grid_power = microgrid.grid().power

        production_power_receiver = production_power.new_receiver()
        battery_power_receiver = battery_power.new_receiver()
        battery_soc_receiver = battery_soc.new_receiver()
        ev_charger_power_receiver = ev_charger_power.new_receiver()
        grid_power_receiver = grid_power.new_receiver()

        # State variables to hold the latest known values from each stream
        latest_prod_power: Power | None = None
        latest_battery_power: Power | None = None
        latest_battery_soc: Percentage | None = None
        latest_ev_charger_power: Power | None = None
        latest_grid_power: Power | None = None
        latest_target_power: Power = Power.from_watts(TARGET_POWER)

        tc_control_logic = TcControlLogic(
            battery_pool=battery_pool,
            ev_charger_pool=ev_charger_pool,
            target_power=latest_target_power,
            min_soc=Percentage.from_fraction(MIN_SOC),
        )

        # Use frequenz.channels.select to react to messages from multiple sources
        selection = select(
            production_power_receiver,
            battery_power_receiver,
            battery_soc_receiver,
            ev_charger_power_receiver,
            grid_power_receiver,
        )

        _logger.debug("Starting control loop")
        try:
            async for selected in selection:
                # Check which channel has a new message and update state
                if selected.message is None:
                    continue  # Skip if no message is available

                if selected_from(selected, production_power_receiver):
                    latest_prod_power = selected.message.value
                    self._influx_reporter.report_metrics(
                        timestamp=selected.message.timestamp,
                        value=latest_prod_power.as_watts(),
                        metric_name="production_power_watts",
                    )
                if selected_from(selected, battery_power_receiver):
                    latest_battery_power = selected.message.value
                    self._influx_reporter.report_metrics(
                        timestamp=selected.message.timestamp,
                        value=latest_battery_power.as_watts(),
                        metric_name="battery_power_watts",
                    )
                if selected_from(selected, battery_soc_receiver):
                    latest_battery_soc = selected.message.value
                    self._influx_reporter.report_metrics(
                        timestamp=selected.message.timestamp,
                        value=latest_battery_soc.as_fraction(),
                        metric_name="battery_soc",
                    )
                if selected_from(selected, ev_charger_power_receiver):
                    latest_ev_charger_power = selected.message.value
                    self._influx_reporter.report_metrics(
                        timestamp=selected.message.timestamp,
                        value=latest_ev_charger_power.as_watts(),
                        metric_name="battery_soc",
                    )
                if selected_from(selected, grid_power_receiver):
                    latest_grid_power = selected.message.value
                    self._influx_reporter.report_metrics(
                        timestamp=selected.message.timestamp,
                        value=latest_grid_power.as_watts(),
                        metric_name="grid_power_watts",
                    )

                # --- Run Control Logic ---
                # We only run the control logic when we get a new grid power value.
                if selected_from(selected, grid_power_receiver):
                    # For now we skip the control logic if data is missing
                    if (
                        latest_prod_power is None
                        or latest_battery_soc is None
                        or latest_grid_power is None
                    ):
                        _logger.warning(
                            "Received None from one of the streams, skipping control logic."
                        )
                        continue
                    await tc_control_logic.run(
                        latest_grid_power, latest_battery_power, latest_battery_soc
                    )
        finally:
            # Ensure the InfluxDB client is closed gracefully
            self._influx_reporter.close()


class EvChargingApp:
    """Application to run the Truck Charging Actor."""

    def __init__(self):
        """Initialize this app."""
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        """Run the application."""
        _logger.info("Starting Power Controller App...")

        await microgrid.initialize(
            MICROGRID_API_URL,
            ResamplerConfig(
                resampling_period=timedelta(seconds=1),
            ),
        )

        await run(TruckChargingActor())


async def main() -> None:
    """Create and run the EvChargingApp."""
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(filename)s:%(lineno)d: %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    if not os.getenv("INFLUXDB3_AUTH_TOKEN"):
        logging.critical(
            "INFLUXDB3_AUTH_TOKEN environment variable not set. Terminating."
        )
        return

    app = EvChargingApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
