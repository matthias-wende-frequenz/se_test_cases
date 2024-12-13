"""Main test application for the Hardware in the Loop (HIL) microgrid simulation

This app and all the test cases are written in the Frequenz python SDK and shall be run
on any machine with access to the Frequenz microgrid API.
"""

import asyncio
import logging

from datetime import timedelta

from frequenz.channels import Broadcast, Sender
from frequenz.sdk import microgrid
from frequenz.sdk.actor import ResamplerConfig, Actor, run

from pymodbus.client import AsyncModbusTcpClient

from se_test_cases.dynamic_condition_on_grid import TestDynamicConditionOnGrid

_logger = logging.getLogger(__name__)

# Connection defaults
GRPC_HOST = "grpc://microgrid.sandbox.api.frequenz.io:62060"
MB_HOST = "127.0.0.1"
MB_PORT = 8502
UNIT_ID = 1
REGISTER_ADDRESS = 1000


async def run_test_case(test_case_actor: Actor) -> None:
    """
    Runs the individual test cases

    Args:
        test_case_actor: The actor that implements the test case.
        test_run_time: The time for which the test case should run.
    """
    _logger.info(f"Running test case: {test_case_actor.name}")
    await run(test_case_actor)
    # _logger.info(f"Test case: {test_case_actor.name} completed.")


def get_test_case_actor_from_int(test_case_id: int) -> Actor | None:
    """
    Returns the test case actor based on the test case id.

    Args:
        test_case_id: The test case id.

    Returns:
        The test case actor.
    """
    test_case_actor_map = {
        1: TestDynamicConditionOnGrid(name="Dynamic Condition On Grid"),
    }
    return test_case_actor_map.get(test_case_id)


async def read_modbus_register(
    host: str,
    port: int,
    unit_id: int,
    register_address: int,
    no_seconds: int,  # rename follow matrix naming convention
    modbus_event_sender: Sender,
) -> int:
    """Reads the value from the Modbus register every n seconds"""
    _logger.info("Initializing connection to Modbus TCP server.")

    client = AsyncModbusTcpClient(host, port=port)
    await client.connect()
    while True:
        _logger.info("Reading Modbus register.")
        result = await client.read_holding_registers(
            address=register_address, count=1, slave=unit_id
        )

        last_register_value = 0

        if result.isError():
            _logger.error(f"Error reading register: {result}")
        else:
            _logger.debug(f"Read result: {result.registers}")
            # check if the value has changed and if so send the value
            if last_register_value != result.registers[0]:
                last_register_value = result.registers[0]
                await modbus_event_sender.send(result.registers[0])

        await asyncio.sleep(no_seconds)


async def run_tests() -> None:
    """Main function to initialize the microgrid and run all the test case actors."""
    _logger.info("Initializing microgrid and connecting to microgrid API.")
    await microgrid.initialize(
        GRPC_HOST,
        ResamplerConfig(resampling_period=timedelta(seconds=1)),
    )

    modbus_event_channel = Broadcast[int](name="modbus_event_channel")

    asyncio.create_task(
        read_modbus_register(
            MB_HOST,
            MB_PORT,
            UNIT_ID,
            REGISTER_ADDRESS,
            5,
            modbus_event_channel.new_sender(),
        )
    )

    # test_case: Actor | None = None

    async for mb_event in modbus_event_channel.new_receiver():
        _logger.info(f"Received Modbus event: {mb_event}")
        # if test_case:
        #     await test_case.stop()
        # test_case = run_test_case(get_test_case_actor_from_int(mb_event)))

    # await run_test_case(
    #     TestDynamicConditionOnGrid(name="Dynamic Condition On Grid"),
    # )
    # await asyncio.sleep(10)


def main() -> None:
    """Main function to run the asyncio event loop."""
    logging.basicConfig(
        level=logging.DEBUG,
    )

    asyncio.run(run_tests())


if __name__ == "__main__":
    main()
