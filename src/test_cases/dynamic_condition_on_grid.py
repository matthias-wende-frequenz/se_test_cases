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
    def __init__ (
            self,
            name,
    ):
        super(). __init__(name=name)
        self._power_values: deque[Power] = deque(maxlen=10)

    async def _run(self):
        power_reader: FormulaEngine[Power] = microgrid.grid().power

        async for power in power_reader.new_receiver():
            if power.value:
                self._power_values.append(power.value)
            print(f"Power Buffer: {self._power_values}")

class VoltActor(Actor):
    def __init__ (
            self,
            name,
    ):
        super().__init__(name=name)
        current_values: deque = deque(maxlen=10)

    async def _run(self):
        voltage_reader = microgrid.voltage_per_phase()


class FreqActor(Actor):
    def __init__ (
            self,
            name,
    ):
        super(). __init__(name=name)

    async def _run(self):
        frequency_reader = microgrid.frequency()

async def main() -> None:
    await microgrid.initialize(
        "grpc://microgrid.sandbox.api.frequenz.io:62060",
        ResamplerConfig(resampling_period=timedelta(seconds=1))
    )

    my_actor = LoadMonitoringActor(name="myactor")
    await run(my_actor)

asyncio.run(main())
