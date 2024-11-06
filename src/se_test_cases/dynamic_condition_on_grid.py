"""Dynamic Condition On-Grid
Validates model for gradual and step changes in load. 
Check Frequency and Voltage response, (limits in P, U, I for different inverters?)
"""

import logging

from collections import deque
from math import sqrt
from enum import Enum

from frequenz.channels import Broadcast, Receiver, select, selected_from
from frequenz.sdk import microgrid
from frequenz.sdk.actor import Actor
from frequenz.sdk.timeseries.formula_engine import FormulaEngine
from frequenz.quantities import Power

_logger = logging.getLogger(__name__)


class LoadChangeCases(Enum):
    """Enum to differentiate between gradual and step load changes."""
    GRADUAL = 1
    STEP = 2


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
        self._load_change_channel = Broadcast[LoadChangeCases](name="gradual_load_change")
        self._load_change_sender = self._load_change_channel.new_sender()

        # Set up Actors to monitor voltage and frequency response
        self._response_checking_actor = ResponseCheckingActor(
            name="response_checking_actor",
            load_change_receiver=self._load_change_channel.new_receiver()
        )
        self._response_checking_actor.start()

    async def _check_gradual_load_change(self) -> None:
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

        if std_deviation > standard_deviation_threshold: 
            await self._load_change_sender.send(LoadChangeCases.GRADUAL)

    async def _check_step_load_change(self) -> None:
        """Check for step load change"""
        await self._load_change_sender.send(LoadChangeCases.STEP)

    async def _run(self):
        grid_power_formula: FormulaEngine[Power] = microgrid.grid().power
        grid_power_receiver = grid_power_formula.new_receiver()

        async for power in grid_power_receiver:
            _logger.info(f"Received new power sample: {power}")
            if power.value:
                # Store the latest power value
                self._power_values.append(power.value)

                # Check for gradual load change and inform other actors about gradual load change
                await self._check_gradual_load_change()
                # Check for step load changes inform other actors about step load change
                await self._check_step_load_change()


class ResponseCheckingActor(Actor):
    def __init__(self, name: str, load_change_receiver: Receiver[LoadChangeCases]):
        """
        Initialize the actor with a name and a receiver for load change cases.

        Args:
            name (str): Name of the actor.
            load_change_receiver (Receiver[LoadChangeCases]): Receiver for load change cases.
        """
        logging.debug(f"Initializing ResponseCheckingActor with name: {name}")
        super().__init__(name=name)

        # TODO add the type
        self._voltage_values: deque = deque(maxlen=10)
        self._frequency_values: deque[float] = deque(maxlen=10)
        self._load_change_receiver = load_change_receiver

    def _check_voltage_response(self):
        """Check for responses in the buffered voltage data"""
        pass

    def _check_frequency_response(self):
        """Check for responses in the buffered frequency data"""
        pass

    async def _run(self):
        """
        Update voltage buffer with new values and check for
        voltage response when triggered by LoadMonitoringActor.
        """
        grid_voltage_formula = microgrid.voltage_per_phase()
        grid_voltage_receiver = grid_voltage_formula.new_receiver()

        frequency_formula = microgrid.frequency()
        frequency_receiver = frequency_formula.new_receiver()

        async for selected in select(self._load_change_receiver, grid_voltage_receiver, frequency_receiver):
            if selected_from(selected, self._load_change_receiver):
                _logger.info(f"Received load change response: {selected.message}")
                self._check_voltage_response()
                self._check_frequency_response()
            elif selected_from(selected, grid_voltage_receiver):
                _logger.debug(f"Received new voltage sample: {selected.message}")
                # TODO do something with the voltage values
                self._voltage_values.append(selected.message)
            elif selected_from(selected, frequency_receiver):
                _logger.debug(f"Received new frequency sample: {selected.message}")
                self._voltage_values.append(selected.message.value)
