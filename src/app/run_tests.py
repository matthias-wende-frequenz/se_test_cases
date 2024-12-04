"""Main test application for the Hardware in the Loop (HIL) microgrid simulation

This app and all the test cases are written in the Frequenz python SDK and shall be run
on any machine with access to the Frequenz microgrid API.
"""

import asyncio
import logging

from datetime import timedelta

from frequenz.sdk import microgrid
from frequenz.sdk.actor import ResamplerConfig, Actor, run

from se_test_cases.dynamic_condition_on_grid import TestDynamicConditionOnGrid

_logger = logging.getLogger(__name__)


async def run_test_case(test_case_actor: Actor, test_run_time: timedelta) -> None:
    """
    Runs the individual test cases

    Args:
        test_case_actor: The actor that implements the test case.
        test_run_time: The time for which the test case should run.
    """
    _logger.info(f"Running test case: {test_case_actor.name}")
    await run(test_case_actor)
    _logger.info(f"Test case: {test_case_actor.name} completed.")


async def run_all_tests() -> None:
    """Main function to initialize the microgrid and run all the test case actors."""
    _logger.info("Initializing microgrid and connecting to microgrid API.")
    await microgrid.initialize(
        "grpc://192.168.1.1:62060",
        ResamplerConfig(resampling_period=timedelta(seconds=1)),
    )

    await run_test_case(
        TestDynamicConditionOnGrid(name="Dynamic Condition On Grid"),
        timedelta(seconds=10),
    )


def main() -> None:
    """Main function to run the asyncio event loop."""
    logging.basicConfig(
        level=logging.INFO,
    )

    asyncio.run(run_all_tests())


if __name__ == "__main__":
    main()
