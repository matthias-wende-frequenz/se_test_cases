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


def get_test_case_actor(test_case: int) -> Actor | None:
    """
    Returns the test case actor based on the test case.

    Args:
        test_case: The test case.

    Returns:
        The test case actor.
    """
    match test_case:
        case 1:
            return TestDynamicConditionOnGrid(name="Dynamic Condition On Grid")
        case _:
            return None


async def read_modbus_register(
    host: str,
    port: int,
    unit_id: int,
    register_address: int,
    no_seconds: int,  # rename follow matrix naming convention
    modbus_event_sender: Sender,
) -> int:
    """
    Reads the value from the Modbus register every n seconds.
    If a register value changes, it sends the value to the Modbus event channel.

    Args:
        host: The IP address of the Modbus server.
        port: The port of the Modbus server.
        unit_id: The Modbus unit ID.
        register_address: The address of the register to read.
        no_seconds: The number of seconds to wait between each read.
        modbus_event_sender: The sender to send the Modbus event.

    Returns:
        The value of the register.
    """
    _logger.info("Initializing connection to Modbus TCP server.")

    client = AsyncModbusTcpClient(host, port=port)
    await client.connect()

    first_run = True
    last_register_value = 0

    while True:
        _logger.info("Reading Modbus register.")
        result = await client.read_holding_registers(
            address=register_address, count=1, slave=unit_id
        )

        if result.isError():
            _logger.error(f"Error reading register: {result}")
        else:
            _logger.debug(f"Modbus Read result: {result.registers}")
            # check if the value has changed and if so send the value
            if first_run:
                last_register_value = result.registers[0]
                first_run = False
            if last_register_value != result.registers[0]:
                last_register_value = result.registers[0]
                await modbus_event_sender.send(result.registers[0])

        await asyncio.sleep(no_seconds)


async def run_tests() -> None:
    """
    Main function to initialize the connection to the microgrid, a modbus reader and
    run a test case if the modbus value changes.
    """
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

    test_case_actor: Actor | None = None

    async for mb_event in modbus_event_channel.new_receiver():
        _logger.info(f"Received event from modbus reader: {mb_event}")

        # Stop the current test case if it is running.
        if test_case_actor:
            _logger.info("Stopping current test case.")
            await test_case_actor.stop()

        # Start the new test case.
        test_case_actor = get_test_case_actor(mb_event)

        if test_case_actor:
            _logger.info(f"Starting test case: {test_case_actor.name}")
            asyncio.create_task(run(test_case_actor))
        else:
            _logger.error(f"Test case not found for event: {mb_event}")


def main() -> None:
    """Main function to run the asyncio event loop."""
    logging.basicConfig(
        level=logging.DEBUG,
    )

    asyncio.run(run_tests())


if __name__ == "__main__":
    main()
