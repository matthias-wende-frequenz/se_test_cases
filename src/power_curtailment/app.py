"""
Power curtailment application to limit power consumption during set price limits.
"""

import asyncio
import logging
import os
import pathlib
import tomllib
from dataclasses import field
from datetime import datetime, timezone
from typing import Any, ClassVar, Type

import click
from frequenz.client.dispatch import DispatchApiClient as DispatchClient
from frequenz.sdk import actor
from marshmallow import Schema
from marshmallow_dataclass import dataclass

from .power_curtailment import PowerCurtailmentActor
from .config import PowerCurtailmentConfig

logger = logging.getLogger(__name__)

CONFIG_FILE = "./configs/power_curtailment_config.toml"


@dataclass
class AppConfig:
    """Configuration for the power curtailment application."""

    power_curtailment_actor_config: PowerCurtailmentConfig = field(
        metadata={
            "metadata": {
                "description": "The base configuration for the PowerCurtailmentActor"
            },
            "required": True,
        },
    )

    start_time: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
        metadata={
            "metadata": {
                "description": "The start time of the application, used for scheduling."
            },
            "required": False,
        },
    )

    dry_run: bool = field(
        default=False,
        metadata={
            "metadata": {
                "description": "dry_run: Run app in dry run mode. Dispatches won't have any effect."
            },
            "required": False,
        },
    )

    Schema: ClassVar[Type[Schema]] = Schema

    @classmethod
    def load_from_file(cls, config_path: pathlib.Path) -> Any:
        """
        Load and validate configuration settings from a TOML file.

        Args:
            config_path: the path to the TOML configuration file.

        Returns:
            the configuration settings if they are valid.
        """
        with open(config_path, "rb") as config_stream:
            settings = tomllib.load(config_stream)

        return cls.Schema().load(settings)


def get_env_variable(name: str) -> str:
    """Get an environment variable.

    Args:
        name: The name of the environment variable to retrieve.

    Returns:
        The value of the environment variable.

    Raises:
        ValueError: If the environment variable is not set.
    """
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"Environment variable '{name}' is not set.")
    logger.debug("Loaded environment variable '%s'.", name)
    return value


# pylint: disable=too-many-locals
async def run(config_path: pathlib.Path) -> None:
    """Run the PowerCurtailmentActor application using TOML configuration.

    Args:
        config_path: Path to the configuration file.
    """
    logger.info("Starting the PowerCurtailmentActor application...")

    try:
        dispatch_api_key = get_env_variable("DISPATCH_API_KEY")
        dispatch_api_address = get_env_variable("DISPATCH_API_URL")
        entsoe_key = get_env_variable("ENTSOE_KEY")

    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return

    app_config: AppConfig = AppConfig.load_from_file(config_path)
    if not app_config:
        logger.error("Failed to load application configuration.")
        return

    logger.info("Application configuration loaded successfully: %s", app_config)

    if app_config.start_time > datetime.now(timezone.utc):
        sleep_duration = (app_config.start_time - datetime.now(timezone.utc)).total_seconds()
        logger.warning(
            "The application start time (%s) is in the future. "
            "Sleeping for %.1f seconds until start time.",
            app_config.start_time,
            sleep_duration,
        )
        await asyncio.sleep(sleep_duration)

    logger.info("Initializing dispatch client...")

    dispatch_client = DispatchClient(
        server_url=str(dispatch_api_address),
        auth_key=dispatch_api_key,
    )
    logger.info("Dispatch api client initialized with url: %s", dispatch_api_address)

    logger.info("Creating PowerCurtailmentActor...")
    power_curtailment_actor = PowerCurtailmentActor(
        config=app_config.power_curtailment_actor_config,
        dispatch_client=dispatch_client,
        entsoe_key=entsoe_key,
        dry_run=app_config.dry_run,
    )

    logger.info("PowerCurtailmentActor initialized. Starting...")

    await actor.run(power_curtailment_actor)


@click.command()
@click.option(
    "--config",
    "config_path",
    default=CONFIG_FILE,
    multiple=False,
    type=click.Path(exists=True, path_type=pathlib.Path),
    help="File path of the config TOML to use.",
)
def main(config_path: pathlib.Path) -> None:
    """Run the ChargeCurtailmentActor application.

    Args:
        config_path: Path of the configuration file to read.
    """
    asyncio.run(run(config_path))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s:%(lineno)d: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    main()  # pylint: disable=no-value-for-parameter
