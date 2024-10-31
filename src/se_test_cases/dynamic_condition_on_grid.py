"""Dynamic Condition On-Grid
Validates model for gradual and step changes in load. 
Check Frequency and Voltage response, (limits in P, U, I for different inverters?)
"""

import logging

from collections import deque

from frequenz.sdk import microgrid
from frequenz.sdk.actor import Actor
from frequenz.sdk.timeseries.formula_engine import FormulaEngine
from frequenz.quantities import Power

_logger = logging.getLogger(__name__)


class TestDynamicConditionOnGrid(Actor):
    """Actor to monitor the grid load and inform othor actors about gradual or step load changes"""

    def __init__(self, name: str):
        super().__init__(name=name)
        self._power_values: deque[Power] = deque(maxlen=10)

    def check_gradual_load_change(self) -> bool:
        """Check for gradual load change"""
        # Set a threshold for the standard deviation
        standard_deviation_threshold = 1 
        # Calculate mean value in the deque
        average_power = sum(self._power_values) / len(self._power_values) if self._power_values else 0  
        # Calculate the standard deviation 
        std_deviation = (sum((x - average_power) ** 2 for x in self._power_values) / len(self._power_values)) ** 0.5   
  
        # Return True if the change is above the threshold  
        return std_deviation > standard_deviation_threshold 
    
        #return True

    def check_step_load_change(self) -> bool:
        """Check for step load change"""
        return True

    async def _run(self):
        grid_power_formula: FormulaEngine[Power] = microgrid.grid().power
        grid_power_receiver = grid_power_formula.new_receiver()

        async for power in grid_power_receiver:
            _logger.info(f"Received new power sample: {power}")
            if power.value:
                # Store the latest power value
                self._power_values.append(power.value)

                # Check for gradual load change
                if self.check_gradual_load_change():
                    # ... Inform other actors about gradual load change
                    pass

                # Check for step load changes
                if self.check_step_load_change():
                    # ... Inform other actors about step load change
                    pass


class VoltageResponseActor(Actor):
    def __init__(self, name):
        super().__init__(name=name)
        self._voltage_values: deque = deque(maxlen=10)

    def _check_voltage_response(self):
        """Check for responses in the buffered voltage data"""
        pass

    async def _run(self):
        """
        Update voltage buffer with new values and check for
        voltage response when triggered by LoadMonitoringActor.
        """
        voltage_formula = microgrid.voltage_per_phase()


class FrequencyResponseActor(Actor):
    def __init__(self, name):
        super().__init__(name=name)
        self._frequency_values: deque = deque(maxlen=10)

    def _check_frequency_response(self):
        """Check for responses in the buffered frequency data"""
        pass

    async def _run(self):
        """
        Update frequency buffer with new values and check for
        frequency response when triggered by LoadMonitoringActor.
        """
        frequency_formula = microgrid.frequency()
