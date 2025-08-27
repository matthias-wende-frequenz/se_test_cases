import asyncio
import logging
import os
import pathlib
import sys
import tomllib
from datetime import datetime, timedelta, timezone

from frequenz.channels import Broadcast, Receiver, select, selected_from
from frequenz.quantities import Percentage, Power
from frequenz.sdk import microgrid
from frequenz.sdk.actor import Actor, ResamplerConfig, run
from frequenz.sdk.timeseries.battery_pool import BatteryPool
from frequenz.sdk.timeseries.ev_charger_pool import EVChargerPool

from .config import Config
# Import the new InfluxReporter class
from .influx_reporter import InfluxReporter

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
_logger = logging.getLogger(__name__)


# Define path to the configuration file
CONFIG_PATH = pathlib.Path("config.toml")

# Define the microgrid API URL
MICROGRID_API_URL = os.getenv("MICROGRID_API_URL", "grpc://[::1]:8800")


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

    async def perform(
        self,
        latest_grid_power: Power,
        latest_battery_power: Power | None,
        latest_battery_soc: Percentage,
        latest_battery_max_discharge_power: Power,
        latest_ev_charger_power: Power | None = None,
        latest_ev_charger_max_power: Power = Power.zero(),
    ) -> None:
        """The main truck charging control logic.

        This method is supposed to be run whenever we receive a new measurement from a meter
        placed at the PCC.
        """
        # --- Flowchart Logic Implementation ---
        if latest_grid_power > self._target_power:
            if latest_battery_soc > self._min_soc:
                latest_battery_power = (
                    latest_battery_power
                    if latest_battery_power is not None
                    else Power.zero()
                )

                _logger.debug("Latest grid power: %s", latest_grid_power)
                _logger.debug("Target power: %s", self._target_power)

                restrict_power = latest_grid_power - self._target_power

                _logger.debug("Restrict power by: %s", restrict_power)
                _logger.debug(
                    "Max discharge Power: %s", latest_battery_max_discharge_power
                )

                battery_discharge_power = max(
                    -restrict_power, latest_battery_max_discharge_power
                )

                _logger.debug("Battery discharge power: %s", battery_discharge_power)

                # As soon as restrict power is bigger than the max discharge power, we need to restrict the EVs
                # Note: latest_battery_max_discharge_power is negative and restrict_power is
                # necessarily positive in this branch, so we need to add it to the restrict power
                ev_restriction_power = max(
                    restrict_power + latest_battery_max_discharge_power, Power.zero()
                )

                _logger.debug("EV restriction power: %s", ev_restriction_power)
                _logger.debug("EV max power: %s", latest_ev_charger_max_power)

                ev_charge_power = max(
                    latest_ev_charger_max_power - ev_restriction_power, Power.zero()
                )

                _logger.debug("EV charge power: %s", ev_charge_power)

                # Discharge Battery & Restrict EV
                await self._battery_pool.propose_power(battery_discharge_power)
                await self._ev_charger_pool.propose_power(ev_charge_power)
            else:
                # Restrict EV Power only
                ev_restriction_power = max(
                    latest_ev_charger_max_power
                    - (latest_grid_power - self._target_power),
                    Power.zero(),
                )
                _logger.debug("Latest Battery SOC: %s", latest_battery_soc)
                _logger.debug("Restrict EV power to: %s", ev_restriction_power)

                await self._ev_charger_pool.propose_power(ev_restriction_power)
        else:
            if latest_grid_power < Power.zero():  # Excess power is exported
                # Charge Battery with excess power only
                _logger.info("Charging battery with excess power.")
                await self._battery_pool.propose_power(-latest_grid_power)
            else:
                _logger.debug("No control action needed.")

            await self._ev_charger_pool.propose_power(latest_ev_charger_max_power)


class TruckChargingActor(Actor):
    """Actor that implements the control logic for the EV charging system."""

    def __init__(
        self,
        config: Config,
        config_rx: Receiver[Config | Exception | None],
    ):
        """Initialize the TruckChargingActor."""
        super().__init__()
        self._config = config
        self._config_receiver = config_rx
        # Instantiate the InfluxReporter
        self._influx_reporter = InfluxReporter()
        self._target_power = self._config.target_power
        self._tc_control_logic: TcControlLogic | None = None
        _logger.info("TruckChargingActor initialized.")

    async def _run(self) -> None:
        """Run the main actor logic."""
        # Get the high-level pools from the microgrid
        battery_pool = microgrid.new_battery_pool(priority=1)
        ev_charger_pool = microgrid.new_ev_charger_pool(priority=1)
        await ev_charger_pool.propose_power(self._target_power)
        await asyncio.sleep(2)
        await ev_charger_pool.propose_power(self._target_power)

        # get the data receivers for the relevant channels
        production_power = microgrid.producer().power
        battery_power = battery_pool.power
        battery_power_status = battery_pool.power_status
        battery_soc = battery_pool.soc
        ev_charger_power = ev_charger_pool.power
        ev_power_status = ev_charger_pool.power_status
        grid_power = microgrid.grid().power

        production_power_receiver = production_power.new_receiver()
        battery_power_receiver = battery_power.new_receiver()
        battery_power_status_receiver = battery_power_status.new_receiver()
        battery_soc_receiver = battery_soc.new_receiver()
        ev_charger_power_receiver = ev_charger_power.new_receiver()
        ev_power_status_receiver = ev_power_status.new_receiver()
        grid_power_receiver = grid_power.new_receiver()

        # State variables to hold the latest known values from each stream
        latest_prod_power: Power | None = None
        latest_battery_power: Power | None = None
        latest_battery_soc: Percentage | None = None
        latest_battery_max_discharge_power: Power = Power.zero()
        latest_ev_charger_power: Power | None = None
        latest_ev_charger_max_power: Power = Power.zero()
        latest_grid_power: Power | None = None

        self._tc_control_logic = TcControlLogic(
            battery_pool=battery_pool,
            ev_charger_pool=ev_charger_pool,
            target_power=self._target_power,
            min_soc=self._config.min_soc,
        )

        # Use frequenz.channels.select to react to messages from multiple sources
        selection = select(
            production_power_receiver,
            battery_power_receiver,
            battery_soc_receiver,
            battery_power_status_receiver,
            ev_charger_power_receiver,
            ev_power_status_receiver,
            grid_power_receiver,
            self._config_receiver,
        )

        _logger.debug("Starting control loop")
        try:
            async for selected in selection:
                # Check which channel has a new message and update state
                if selected.message is None:
                    continue  # Skip if no message is available

                if selected_from(selected, self._config_receiver):
                    new_config = selected.message
                    if isinstance(new_config, Config):
                        self._config = new_config
                        self._target_power = self._config.target_power
                        if self._tc_control_logic:
                            self._tc_control_logic.set_target_power(self._target_power)
                        _logger.info("Configuration updated.")
                    else:
                        _logger.warning("Received invalid config update.")
                    continue

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
                if selected_from(selected, battery_power_status_receiver):
                    latest_battery_bounds = selected.message.bounds
                    latest_battery_max_discharge_power = (
                        latest_battery_bounds.lower
                        if latest_battery_bounds
                        else Power.zero()
                    )
                    self._influx_reporter.report_metrics(
                        timestamp=datetime.now(tz=timezone.utc),
                        value=latest_battery_max_discharge_power.as_watts(),
                        metric_name="battery_max_discharge_power_watts",
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
                        metric_name="ev_charger_power_watts",
                    )
                if selected_from(selected, ev_power_status_receiver):
                    latest_ev_charger_max_power = selected.message.bounds
                    latest_ev_charger_max_power = (
                        latest_ev_charger_max_power.upper
                        if latest_ev_charger_max_power
                        else Power.zero()
                    )
                    self._influx_reporter.report_metrics(
                        timestamp=datetime.now(tz=timezone.utc),
                        value=latest_ev_charger_max_power.as_watts(),
                        metric_name="ev_charger_max_power_watts",
                    )
                if selected_from(selected, grid_power_receiver):
                    latest_grid_power = selected.message.value
                    logging.debug(
                        f"Received grid power: {latest_grid_power.as_watts()} W"
                    )
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
                    await self._tc_control_logic.perform(
                        latest_grid_power,
                        latest_battery_power,
                        latest_battery_soc,
                        latest_battery_max_discharge_power,
                        latest_ev_charger_power,
                        latest_ev_charger_max_power,
                    )
        finally:
            # Ensure the InfluxDB client is closed gracefully
            self._influx_reporter.close()


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

    # Silence the noisy SDK logger
    logging.getLogger("frequenz.sdk.microgrid._old_component_data").setLevel(60)

    if len(sys.argv) >= 2:
        config_path = pathlib.Path(sys.argv[1])
        with open(config_path, "rb") as f:
            config_dict = tomllib.load(f)

        actor_config = Config.create(config_dict)
    else:
        # Use default configuration
        actor_config = Config()

    await microgrid.initialize(
        MICROGRID_API_URL,
        ResamplerConfig(resampling_period=timedelta(seconds=1)),
    )

    config_channel = Broadcast[Config | Exception | None](name="config_channel")
    actor = TruckChargingActor(
        config=actor_config,
        config_rx=config_channel.new_receiver(),
    )
    await run(actor)


if __name__ == "__main__":
    asyncio.run(main())
