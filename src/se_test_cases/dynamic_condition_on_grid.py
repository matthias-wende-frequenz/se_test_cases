"""Dynamic Condition On-Grid
Validates model for gradual and step changes in load. 
Check Frequency and Voltage response, (limits in P, U, I for different inverters?)
"""

import logging

from collections import deque
from math import sqrt
from enum import Enum

from frequenz.channels import Broadcast, Receiver, Sender, select, selected_from
from frequenz.sdk import microgrid
from frequenz.sdk.actor import Actor
from frequenz.sdk.timeseries.formula_engine import FormulaEngine
from frequenz.quantities import Frequency, Power

_logger = logging.getLogger(__name__)


class LoadChangeCases(Enum):
    """Enum to differentiate between gradual and step load changes."""

    GRADUAL = 1
    STEP = 2


class TestState(Enum):
    """Enum to differentiate between different states of the test."""

    GRADUAL_LOAD_CHANGE = 1
    STEP_LOAD_CHANGE = 2


class TestDynamicConditionOnGrid(Actor):
    """Actor to monitor the grid load and inform othor actors about gradual or step load changes."""

    def __init__(self, name: str):
        """
        Initialize the actor with a name and set up broadcast channels for gradual and step load changes.

        Args:
            name (str): Name of the actor.
        """
        super().__init__(name=name)
        self._power_values: deque[Power] = deque(maxlen=10)

        # Set up broadcast channels for gradual and step load changes
        self._load_change_channel = Broadcast[LoadChangeCases](
            name="gradual_load_change"
        )
        self._load_change_sender = self._load_change_channel.new_sender()
        # Set up finished channel to inform the actor that the test is completed
        self._finished_channel = Broadcast[bool](name="finished")
        self._finished_receiver = self._finished_channel.new_receiver()

        # Set up Actors to monitor voltage and frequency response
        self._response_checking_actor = ResponseCheckingActor(
            name="response_checking_actor",
            load_change_receiver=self._load_change_channel.new_receiver(),
            finshed_sender=self._finished_channel.new_sender(),
        )
        self._response_checking_actor.start()

        # Set the initial state of the test
        self._test_state = TestState.GRADUAL_LOAD_CHANGE

    async def _check_gradual_load_change(self) -> bool:
        """Check for gradual load change"""
        # Set a threshold for the standard deviation
        standard_deviation_threshold = 1
        # Calculate mean value in the deque
        average_power = (
            sum(self._power_values, Power.zero()) / float(len(self._power_values))
            if self._power_values
            else Power.zero()
        )
        # Calculate the standard deviation
        std_deviation = sqrt(
            sum(
                (x.base_value - average_power.base_value) ** 2
                for x in self._power_values
            )
            / float(len(self._power_values))
        )

        return std_deviation > standard_deviation_threshold

    async def _check_step_load_change(self) -> bool:
        """Check for step load change"""
        return True

    async def _run(self):
        """Monitor the grid power and inform other actors about gradual or step load changes."""

        grid_power_formula: FormulaEngine[Power] = microgrid.grid().power
        grid_power_receiver = grid_power_formula.new_receiver()

        async for power in grid_power_receiver:
            _logger.debug(f"Received new power sample: {power}")
            if power.value:
                # Store the latest power value
                self._power_values.append(power.value)

                match self._test_state:
                    case TestState.GRADUAL_LOAD_CHANGE:
                        # Check for gradual load change and inform other actors about gradual load change
                        if await self._check_gradual_load_change():
                            _logger.info("Gradual load change detected")
                            await self._load_change_sender.send(LoadChangeCases.GRADUAL)
                            self._test_state = TestState.STEP_LOAD_CHANGE
                    case TestState.STEP_LOAD_CHANGE:
                        # Check for step load changes inform other actors about step load change
                        if await self._check_step_load_change():
                            await self._load_change_sender.send(LoadChangeCases.STEP)
                            # Wait for all tests to finish and stop the actor
                            await self._finished_receiver.receive()
                            await self.stop()


class ResponseCheckingActor(Actor):
    def __init__(
        self,
        name: str,
        load_change_receiver: Receiver[LoadChangeCases],
        finshed_sender: Sender[bool],
    ):
        """
        Initialize the actor with a name and a receiver for load change cases.

        Args:
            name (str): Name of the actor.
            load_change_receiver (Receiver[LoadChangeCases]): Receiver for load change cases.
            finshed_sender (Sender[bool]): Sender to inform the actor that the test is completed.
        """
        logging.debug(f"Initializing ResponseCheckingActor with name: {name}")
        super().__init__(name=name)

        # TODO add the type
        self._voltage_values: deque = deque(maxlen=10)
        self._frequency_values: deque[Frequency] = deque(maxlen=10)
        self._load_change_receiver = load_change_receiver
        self._finished_sender = finshed_sender

    def _check_voltage_response(self) -> bool:
        """Check for responses in the buffered voltage data"""
        return True

    def _check_frequency_response(self):
        """Check for responses in the buffered frequency data"""
        return True

    async def _run(self):
        """
        Update voltage buffer with new values and check for
        voltage response when triggered by LoadMonitoringActor.
        """
        grid_voltage_formula = microgrid.voltage_per_phase()
        grid_voltage_receiver = grid_voltage_formula.new_receiver()

        frequency_formula = microgrid.frequency()
        frequency_receiver = frequency_formula.new_receiver()

        async for selected in select(
            self._load_change_receiver, grid_voltage_receiver, frequency_receiver
        ):
            if selected_from(selected, self._load_change_receiver):
                _logger.info(
                    "Checking voltage and frequency responses for case: {selected.message}"
                )
                if self._check_voltage_response():
                    _logger.info("Voltage response test: SUCESS.")
                else:
                    _logger.error("Voltage response test: FAILED.")
                if self._check_frequency_response():
                    _logger.info("Frequency response test: SUCESS.")
                else:
                    _logger.error("Frequency response test: FAILED.")

                # Stop the actor after all tests are completed
                if selected.message == LoadChangeCases.STEP:
                    await self._finished_sender.send(True)
                    await self.stop()
            elif selected_from(selected, grid_voltage_receiver):
                _logger.debug(f"Received new voltage sample: {selected.message}")
                # TODO do something with the voltage values
                self._voltage_values.append(selected.message)
            elif selected_from(selected, frequency_receiver):
                _logger.debug(f"Received new frequency sample: {selected.message}")
                if selected.message.value:
                    self._frequency_values.append(selected.message.value)
