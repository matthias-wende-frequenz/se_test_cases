import asyncio
import logging
import pathlib
from datetime import timedelta

from frequenz.channels import select, selected_from
from frequenz.quantities import Percentage, Power
from frequenz.sdk import microgrid
from frequenz.sdk.actor import Actor, ResamplerConfig, run
from frequenz.sdk.timeseries.battery_pool import BatteryPool

# Configure logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

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

# TODO:
# * [ ] use latest value cache from the channels repo to simplify the code
# * [ ] use the lvc in the control loop logic
# * [ ] move the control loop logic code into a seperate module


class TcControlLogic:
    """Control Logic for the Truck Charging Actor

    TODO: Descripe the control logic in this docstring, render the mermaid to ascii and
    place it here too.
    """

    def __init__(
        self,
        battery_pool: BatteryPool,
        target_power: Power,
        min_soc: Percentage,
    ):
        self._battery_pool = battery_pool
        self._target_power = target_power
        self._min_soc = min_soc

    async def run(
        self,
        latest_grid_power: Power,
        latest_battery_power: Power | None,
        latest_battery_soc: Percentage,
    ):
        """The main truck charging control logic.

        This method is supposed to be run whenever we receive a new measurment from a meter
        placed at the PCC.
        """
        # --- Flowchart Logic Implementation ---
        if latest_grid_power > self._target_power:
            # TODO check signs
            # TODO we need to to use a different formula to calculate the residual power
            #      since it has to incorporate the battery power as well as the EV power

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
        """Initialize the ControlLogicActor."""
        super().__init__()
        _logger.info("TruckChargingActor initialized.")

    async def _run(self) -> None:
        """Run the main actor logic."""
        # Get the high-level pools from the microgrid
        battery_pool = microgrid.new_battery_pool(priority=1)
        # ev_charger_pool = microgrid.new_ev_charger_pool(priority=1)

        # get the data receivers for the relevant channels
        production_power = microgrid.producer().power
        battery_power = battery_pool.power
        battery_soc = battery_pool.soc
        grid_power = microgrid.grid().power
        production_power_receiver = production_power.new_receiver()
        battery_power_receiver = battery_power.new_receiver()
        battery_soc_receiver = battery_soc.new_receiver()
        grid_power_receiver = grid_power.new_receiver()

        # State variables to hold the latest known values from each stream
        # We can simplify that code by using the latest value cache from the channels repo
        latest_prod_power: Power | None = None
        latest_battery_power: Power | None = None
        latest_battery_soc: Percentage | None = None
        latest_grid_power: Power | None = None
        latest_target_power: Power = Power.from_watts(TARGET_POWER)

        tc_control_logic = TcControlLogic(
            battery_pool=battery_pool,
            target_power=latest_target_power,
            min_soc=Percentage.from_fraction(MIN_SOC),
        )

        # Use frequenz.channels.select to react to messages from multiple sources
        selection = select(
            production_power_receiver,
            battery_power_receiver,
            battery_soc_receiver,
            grid_power_receiver,
        )

        _logger.debug("Starting control loop")
        async for selected in selection:
            # Check which channel has a new message
            if selected_from(selected, production_power_receiver):
                latest_prod_power = selected.message.value if selected.message else None
            if selected_from(selected, battery_power_receiver):
                latest_battery_power = (
                    selected.message.value if selected.message else None
                )
            if selected_from(selected, battery_soc_receiver):
                latest_battery_soc = (
                    selected.message.value if selected.message else None
                )
            if selected_from(selected, grid_power_receiver):
                latest_grid_power = selected.message.value if selected.message else None
                # In future we can implement a smarter logic on what to do if there is no data:
                #      * if we have no battery data, we can only restrict EVs
                #      * if we have no grid data, we stop EV chargers or we limit
                #        the charging power and discharge the battery with fixed power
                # For now we skip the control logic
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


class EvChargingApp:
    """Application to run the Truck Charging Actor."""

    def __init__(self):  # , *, config_paths: Sequence[pathlib.Path]):
        """Initialize this app.

        Args:
            config_paths: The paths to the TOML configuration files.
        """
        # self._config_paths = config_paths
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
    """Create and run the ControlLogicApp."""
    # if not CONFIG_PATH.is_file():
    #     logging.critical(f"Configuration file not found at: {CONFIG_PATH}")
    #     return

    app = EvChargingApp()
    # app = EvChargingApp(config_paths=[CONFIG_PATH])
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
