"""Unit tests for the TcControlLogic class."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from frequenz.quantities import Percentage, Power

from app.ev_charging_main import TcControlLogic


@pytest.fixture
def mock_battery_pool():
    """Fixture to create a mock BatteryPool."""
    return AsyncMock()


@pytest.fixture
def mock_ev_charger_pool():
    """Fixture to create a mock EVChargerPool."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_no_control_action_needed(
    mock_battery_pool, mock_ev_charger_pool
):
    """Test that no control action is taken when grid power is below the target."""
    # Test setup
    target_power = Power.from_watts(25000.0)
    min_soc = Percentage.from_fraction(0.1)
    control_logic = TcControlLogic(
        mock_battery_pool, mock_ev_charger_pool, target_power, min_soc
    )

    # Inputs
    latest_grid_power = Power.from_watts(20000.0)
    latest_battery_power = Power.from_watts(0.0)
    latest_battery_soc = Percentage.from_fraction(0.5)

    # Run the control logic
    await control_logic.run(
        latest_grid_power, latest_battery_power, latest_battery_soc
    )

    # Assertions
    mock_battery_pool.propose_power.assert_not_called()


@pytest.mark.asyncio
async def test_discharge_battery_and_restrict_ev(
    mock_battery_pool, mock_ev_charger_pool
):
    """Test that the battery is discharged and EVs are restricted when grid power is high."""
    # Test setup
    target_power = Power.from_watts(25000.0)
    min_soc = Percentage.from_fraction(0.1)
    control_logic = TcControlLogic(
        mock_battery_pool, mock_ev_charger_pool, target_power, min_soc
    )

    # Inputs
    latest_grid_power = Power.from_watts(30000.0)
    latest_battery_power = Power.from_watts(1000.0)
    latest_battery_soc = Percentage.from_fraction(0.5)

    # Run the control logic
    await control_logic.run(
        latest_grid_power, latest_battery_power, latest_battery_soc
    )

    # Assertions
    expected_residual_power = (
        latest_grid_power + latest_battery_power
    ) - target_power
    mock_battery_pool.propose_power.assert_called_once_with(
        expected_residual_power
    )


@pytest.mark.asyncio
async def test_restrict_ev_only_when_battery_is_low(
    mock_battery_pool, mock_ev_charger_pool
):
    """Test that only EVs are restricted when grid power is high and battery is low."""
    # Test setup
    target_power = Power.from_watts(25000.0)
    min_soc = Percentage.from_fraction(0.1)
    control_logic = TcControlLogic(
        mock_battery_pool, mock_ev_charger_pool, target_power, min_soc
    )

    # Inputs
    latest_grid_power = Power.from_watts(30000.0)
    latest_battery_power = Power.from_watts(1000.0)
    latest_battery_soc = Percentage.from_fraction(0.05)  # Low SoC

    # Run the control logic
    await control_logic.run(
        latest_grid_power, latest_battery_power, latest_battery_soc
    )

    # Assertions
    mock_battery_pool.propose_power.assert_not_called()
    residual_power = latest_grid_power - target_power
    mock_ev_charger_pool.propose_power.assert_called_once_with(residual_power)


@pytest.mark.asyncio
async def test_charge_battery_with_excess_power(
    mock_battery_pool, mock_ev_charger_pool
):
    """Test that the battery is charged with excess power when grid power is negative."""
    # Test setup
    target_power = Power.from_watts(25000.0)
    min_soc = Percentage.from_fraction(0.1)
    control_logic = TcControlLogic(
        mock_battery_pool, mock_ev_charger_pool, target_power, min_soc
    )

    # Inputs
    latest_grid_power = Power.from_watts(-5000.0)  # Excess power
    latest_battery_power = Power.from_watts(0.0)
    latest_battery_soc = Percentage.from_fraction(0.5)

    # Run the control logic
    await control_logic.run(
        latest_grid_power, latest_battery_power, latest_battery_soc
    )

    # Assertions
    charging_power = latest_grid_power + latest_battery_power
    mock_battery_pool.propose_power.assert_called_once_with(charging_power)
