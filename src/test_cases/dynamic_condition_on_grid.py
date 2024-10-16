"""Dynamic Condition On-Grid
Validates model for gradual and step changes in load. 
Check Frequency and Voltage response, (limits in P, U, I for different inverters?)
"""

import asyncio

from frequenz.sdk.actor import Actor, run, ResamplerConfig
from frequenz.sdk import microgrid
from frequenz.sdk.timeseries import Power
from frequenz.sdk.timeseries.formula_engine import FormulaEngine
from datetime import timedelta
from collections import deque


class LoadMonitoringActor(Actor):
    """Actor to monitor the grid load and inform othor actors about gradual or step load changes"""

    def __init__(self, name):
        super().__init__(name=name)
        self._power_values: deque[Power] = deque(maxlen=10)

    def check_gradual_load_change(self) -> bool:
        """Check for gradual load change"""
        return True

    def check_step_load_change(self) -> bool:
        """Check for step load change"""
        return True

    async def _run(self):
        power_reader: FormulaEngine[Power] = microgrid.grid().power

        async for power in power_reader.new_receiver():
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
        voltage_reader = microgrid.voltage_per_phase()


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
        frequency_reader = microgrid.frequency()


async def run() -> None:
    """Main function to initialize the microgrid, set up channels and run the actors"""
    await microgrid.initialize(
        "grpc://microgrid.sandbox.api.frequenz.io:62060",
        ResamplerConfig(resampling_period=timedelta(seconds=1)),
    )

    my_actor = LoadMonitoringActor(name="myactor")
    await run(my_actor)

def main() -> None:
    asyncio.run(run())

if __name__ == "__main__":
    main()
