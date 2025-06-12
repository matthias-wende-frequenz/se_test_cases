import asyncio
import logging
import pathlib

from collections.abc import Sequence

from frequenz.sdk import microgrid
from frequenz.sdk.actor import Actor
from frequenz.sdk.actor import ResamplerConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)

# Define path to the configuration file
CONFIG_PATH = pathlib.Path("config.toml")

# Define the TARGET_POWER constant (should be defined in the config or come from a dispatch event)
TARGET_POWER = 25000.0  # Default target power in watts

_logger = logging.getLogger(__name__)


class TruckChargingActor(Actor):
    """Actor that implements the control logic for the EV charging system."""

    def __init__(self):
        """Initialize the ControlLogicActor."""
        super().__init__()
        _logger.info("ControlLogicActor initialized.")

    async def _run(self) -> None:
        """Run the main actor logic."""
        _logger.info("Control Logic Actor is running.")

        # Get the high-level pools from the PowerDistributor
        battery_pool = self._power_distributor.battery_pool
        ev_charger_pool = self._power_distributor.ev_charger_pool

        if battery_pool is None or ev_charger_pool is None:
            _logger.error(
                "Required battery or EV charger pools not available. Exiting."
            )
            return

        # Use frequenz.channels.Select to react to messages from multiple sources
        select = Select(
            generated_power=self._power_distributor.pv_production_power,
            battery_soc=battery_pool.soc,
            grid_power=self._power_distributor.grid_power,
            dispatch_msg=self._dispatcher.new_receiver(DISPATCH_TARGET_POWER),
        )

        # State variables to hold the latest known values from each stream
        latest_gen_power: float | None = None
        latest_battery_soc: float | None = None
        latest_grid_power: float | None = None
        latest_target_power: float = self.config.default_target_power

        # This is the main control loop, now driven by the Select object
        while await select.ready():
            # Check which channel has a new message
            if msg := select.generated_power.receive():
                latest_gen_power = msg.value
            if msg := select.battery_soc.receive():
                latest_battery_soc = msg.value
            if msg := select.grid_power.receive():
                latest_grid_power = msg.value
            if msg := select.dispatch_msg.receive():
                # A dispatch message could be a simple JSON like: `{"value": 25000.0}`
                if msg.payload and (value := msg.payload.get("value")) is not None:
                    latest_target_power = float(value)
                    _logger.info(f"Received new target power via dispatch: {value} W")

            # Only run the logic if we have received at least one value from each stream
            if any(
                v is None
                for v in [latest_gen_power, latest_battery_soc, latest_grid_power]
            ):
                continue

            # --- Flowchart Logic Implementation ---
            if latest_gen_power > latest_target_power:
                if latest_battery_soc > self.config.min_soc:
                    # P1: Discharge Battery & Restrict EV
                    _logger.info("Action P1: Discharging battery, restricting EVs.")
                    residual_power = latest_gen_power - latest_target_power
                    await battery_pool.set_power_bounds(-1e6, 0.0)
                    await ev_charger_pool.set_power_bounds(0.0, residual_power)
                else:
                    # P3: Restrict EV Power only
                    _logger.info("Action P3: Restricting EV power.")
                    residual_power = latest_gen_power - latest_target_power
                    await ev_charger_pool.set_power_bounds(0.0, residual_power)
            else:
                if latest_grid_power < 0:  # Excess power is exported
                    # P2: Charge Battery
                    _logger.info("Action P2: Charging battery with excess power.")
                    await battery_pool.set_power_bounds(0.0, abs(latest_grid_power))
                else:
                    # No-op: Clear any previous restrictions from our actor
                    _logger.debug("No control action needed. Clearing power bounds.")
                    await battery_pool.set_power_bounds(None, None)
                    await ev_charger_pool.set_power_bounds(None, None)


class EvChargingApp:
    """Application to run the Truck Charging Actor."""

    def __init__(self, *, config_paths: Sequence[pathlib.Path]):
        """Initialize this app.

        Args:
            config_paths: The paths to the TOML configuration files.
        """
        self._config_paths = config_paths
        self._tasks: set[asyncio.Task[None]] = set()

    async def run(self) -> None:
        """Run the application."""
        _logger.info("Starting Power Controller App...")

        await microgrid.initialize(
            self._env_config.MICROGRID_API_URL,
            ResamplerConfig(
                resampling_period=1,
            ),
        )

        controller = TruckChargingActor()
        controller.start()

        # Wait for all tasks to complete (runs forever)
        await asyncio.gather(*self._tasks)


async def main() -> None:
    """Create and run the ControlLogicApp."""
    if not CONFIG_PATH.is_file():
        logging.critical(f"Configuration file not found at: {CONFIG_PATH}")
        return

    app = EvChargingApp(config_paths=[CONFIG_PATH])
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
