"""Tests for the power_curtailment package."""
# pylint: disable=protected-access
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from power_curtailment.power_curtailment import PowerCurtailmentActor
from power_curtailment.config import PowerCurtailmentConfig


class TestPowerCurtailmentConfig:
    """Test the PowerCurtailmentConfig class."""

    def test_invalid_config_retry_window(self) -> None:
        """Test that config raises error when retry window exceeds run frequency."""
        with pytest.raises(ValueError, match="Invalid schedule"):
            PowerCurtailmentConfig(
                run_frequency=timedelta(minutes=30),
                da_price_frequency="15min",
                microgrid_ids=[1],
                price_limit=100.0,
                retries=5,
                initial_backoff=timedelta(minutes=10),
            )


class TestPowerCurtailmentActor:
    """Test the PowerCurtailmentActor."""

    @pytest.fixture
    def config(self) -> PowerCurtailmentConfig:
        """Create a test configuration."""
        return PowerCurtailmentConfig(
            run_frequency=timedelta(hours=1),
            da_price_frequency="15min",
            initial_backoff=timedelta(seconds=1),
            microgrid_ids=[1],
            price_limit=100.0,
            power_reduction_w=5000.0,
        )

    @pytest.fixture
    def dispatch_client(self) -> MagicMock:
        """Create a mock dispatch client."""
        return MagicMock()

    @pytest.fixture
    def power_curtailment_actor(
        self, config: PowerCurtailmentConfig, dispatch_client: MagicMock
    ) -> PowerCurtailmentActor:
        """Create a PowerCurtailmentActor instance for testing."""
        with patch("power_curtailment.power_curtailment.EntsoePandasClient"):
            return PowerCurtailmentActor(
                config=config,
                dispatch_client=dispatch_client,
                entsoe_key="test_key",
                dry_run=False,
            )

    @pytest.mark.asyncio
    async def test_price_limit_logic_above_threshold(
        self, power_curtailment_actor: PowerCurtailmentActor
    ) -> None:
        """Test that dispatch is sent when price is ABOVE the limit (charge curtailment logic)."""
        timestamp1 = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")
        timestamp2 = pd.Timestamp("2024-01-01 12:15:00", tz="UTC")

        # Prices: 150.0 > 100.0 (limit) -> should curtail
        #         50.0 < 100.0 (limit) -> should NOT curtail
        mock_prices = pd.Series(
            [150.0, 50.0], index=[timestamp1, timestamp2], name="da_price"
        )

        with patch.object(power_curtailment_actor, "_send_dispatch") as mock_send:
            await power_curtailment_actor._process_available_prices(
                mock_prices, [timestamp1, timestamp2]
            )

            # Should only send dispatch for the high price (150.0 > 100.0)
            mock_send.assert_called_once_with(timestamp1)

            # Both contracts should be marked as processed
            assert power_curtailment_actor._active_contracts[timestamp1] is True
            assert power_curtailment_actor._active_contracts[timestamp2] is True

    @pytest.mark.asyncio
    async def test_price_limit_logic_below_threshold(
        self, power_curtailment_actor: PowerCurtailmentActor
    ) -> None:
        """Test that NO dispatch is sent when all prices are below the limit."""
        timestamp1 = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")
        timestamp2 = pd.Timestamp("2024-01-01 12:15:00", tz="UTC")

        # Both prices below limit (50.0, 75.0 < 100.0) -> no curtailment
        mock_prices = pd.Series(
            [50.0, 75.0], index=[timestamp1, timestamp2], name="da_price"
        )

        with patch.object(power_curtailment_actor, "_send_dispatch") as mock_send:
            await power_curtailment_actor._process_available_prices(
                mock_prices, [timestamp1, timestamp2]
            )

            # No dispatch should be sent
            mock_send.assert_not_called()

            # Both contracts should still be marked as processed
            assert power_curtailment_actor._active_contracts[timestamp1] is True
            assert power_curtailment_actor._active_contracts[timestamp2] is True

    @pytest.mark.asyncio
    async def test_multiple_microgrids_success(
        self, dispatch_client: MagicMock
    ) -> None:
        """Test dispatch to multiple microgrids."""
        config = PowerCurtailmentConfig(
            run_frequency=timedelta(hours=1),
            da_price_frequency="15min",
            microgrid_ids=[1, 2, 3],
            price_limit=100.0,
            power_reduction_w=3000.0,
        )

        async def mock_create(*args, **kwargs):
            return None

        dispatch_client.create = mock_create

        with patch("power_curtailment.power_curtailment.EntsoePandasClient"):
            actor = PowerCurtailmentActor(
                config=config,
                dispatch_client=dispatch_client,
                entsoe_key="test_key",
                dry_run=False,
            )

        timestamp = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")

        result = await actor._send_dispatch(timestamp)

        assert result is True

    @pytest.mark.asyncio
    async def test_partial_microgrid_failure(self, dispatch_client: MagicMock) -> None:
        """Test behavior when some microgrids fail."""
        config = PowerCurtailmentConfig(
            run_frequency=timedelta(hours=1),
            da_price_frequency="15min",
            microgrid_ids=[1, 2],
            price_limit=100.0,
            power_reduction_w=3000.0,
        )

        call_count = 0

        async def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("Dispatch failed")
            return None

        dispatch_client.create = mock_create

        with patch("power_curtailment.power_curtailment.EntsoePandasClient"):
            actor = PowerCurtailmentActor(
                config=config,
                dispatch_client=dispatch_client,
                entsoe_key="test_key",
                dry_run=False,
            )

        timestamp = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")

        result = await actor._send_dispatch(timestamp)

        # Should return False when not all microgrids succeed
        assert result is False

        # Should still try both microgrids
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_unprocessed_contracts_logic(
        self, power_curtailment_actor: PowerCurtailmentActor
    ) -> None:
        """Test that only unprocessed contracts are returned for processing."""
        timestamp1 = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")
        timestamp2 = pd.Timestamp("2024-01-01 12:15:00", tz="UTC")
        timestamp3 = pd.Timestamp("2024-01-01 12:30:00", tz="UTC")

        power_curtailment_actor._active_contracts = {
            timestamp1: False,  # unprocessed
            timestamp2: True,  # processed
            timestamp3: False,  # unprocessed
        }

        unprocessed = power_curtailment_actor._get_unprocessed_contracts()

        assert len(unprocessed) == 2
        assert timestamp1 in unprocessed
        assert timestamp3 in unprocessed
        assert timestamp2 not in unprocessed

    @pytest.mark.asyncio
    async def test_failed_dispatch_not_marked_processed(
        self, power_curtailment_actor: PowerCurtailmentActor
    ) -> None:
        """Test that failed dispatches don't get marked as processed."""
        timestamp = pd.Timestamp("2024-01-01 12:00:00", tz="UTC")

        power_curtailment_actor._active_contracts[timestamp] = False

        mock_prices = pd.Series([150.0], index=[timestamp], name="da_price")

        with patch.object(
            power_curtailment_actor, "_send_dispatch", return_value=False
        ):
            await power_curtailment_actor._process_available_prices(
                mock_prices, [timestamp]
            )

            assert power_curtailment_actor._active_contracts[timestamp] is False
