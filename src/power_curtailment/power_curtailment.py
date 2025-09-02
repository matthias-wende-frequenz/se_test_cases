"""ChargeCurtailmentActor for curtailing charging during negative day-ahead prices."""

import asyncio
import logging
from typing import cast

import pandas as pd
from entsoe import EntsoePandasClient  # type: ignore
from entsoe.exceptions import NoMatchingDataError  # type: ignore
from frequenz.channels.timer import SkipMissedAndDrift, Timer
from frequenz.client.common.microgrid import MicrogridId
from frequenz.client.common.microgrid.components import ComponentCategory
from frequenz.client.dispatch import DispatchApiClient
from frequenz.client.dispatch.types import TargetCategories
from frequenz.sdk.actor import Actor

from .config import PowerCurtailmentConfig

_logger = logging.getLogger(__name__)


class PowerCurtailmentActor(Actor):
    """Actor that curtails power consumption based on day-ahead electricity prices.

    Monitors day-ahead prices and sends dispatches to curtail power
    when prices are above the configured threshold.
    """

    def __init__(
        self,
        *,
        config: PowerCurtailmentConfig,
        dispatch_client: DispatchApiClient,
        entsoe_key: str,
        dry_run: bool,
    ) -> None:
        """Initialize the PowerCurtailmentActor.

        Args:
            config: Configuration object containing all necessary parameters.
            dispatch_client: Client for the Dispatch API.
            entsoe_key: API key for the ENTSO-e client.
            dry_run: Run app in dry run mode. Dispatches won't have any effect.

        """
        super().__init__()
        self._config = config
        self._dispatch_client = dispatch_client
        self._entsoe_key = entsoe_key
        self._dry_run = dry_run
        self._client = EntsoePandasClient(api_key=self._entsoe_key)
        self._active_contracts: dict[pd.Timestamp, bool] = {}
        _logger.info(
            "PowerCurtailmentActor initialized with run_frequency=%s, da_price_frequency=%s,"
            "microgrid_ids=%s",
            config.run_frequency,
            config.da_price_frequency,
            config.microgrid_ids,
        )

    def update_contracts(self) -> None:
        """Update the currently active contracts."""
        now = pd.Timestamp.now(tz="Europe/Berlin")
        tomorrow_midnight = (now + pd.Timedelta(days=2)).normalize()

        current_contracts = pd.date_range(
            start=now.ceil(self._config.da_price_frequency),
            end=tomorrow_midnight,
            freq=self._config.da_price_frequency,
            inclusive="left",
        )

        current_set = set(current_contracts)
        existing_set = set(self._active_contracts.keys())

        removed_count = len(existing_set - current_set)
        for ts in existing_set - current_set:
            del self._active_contracts[ts]

        added_count = len(current_set - existing_set)
        for ts in current_set - existing_set:
            self._active_contracts[ts] = False

        if removed_count > 0 or added_count > 0:
            _logger.info(
                "Updated contracts: %d removed, %d added, %d total active",
                removed_count,
                added_count,
                len(self._active_contracts),
            )

            _logger.info("Active contracts: %s", list(self._active_contracts.keys()))

    async def _run(self) -> None:
        """Run the actor."""
        _logger.info(
            "Starting PowerCurtailmentActor with run_frequency=%s",
            self._config.run_frequency,
        )
        timer = Timer(self._config.run_frequency, SkipMissedAndDrift())
        async for _ in timer:
            self.update_contracts()
            await self._process_contracts_with_retries()

    async def _process_contracts_with_retries(self) -> None:
        """Process contracts with retry mechanism for connectivity issues."""
        attempt = 0
        backoff = self._config.initial_backoff

        while attempt < self._config.retries:
            unprocessed_contracts = self._get_unprocessed_contracts()

            if not unprocessed_contracts:
                _logger.debug("No unprocessed contracts to handle")
                return

            _logger.debug(
                "Processing %d unprocessed contracts", len(unprocessed_contracts)
            )

            # Try to fetch prices for all unprocessed contracts
            start_time = min(unprocessed_contracts)
            end_time = max(unprocessed_contracts) + pd.Timedelta(minutes=1)
            _logger.info("Fetching prices from %s to %s (%d contracts)", start_time, end_time, len(unprocessed_contracts))

            try:
                da_prices = await self._fetch_da_prices(start_time, end_time)
                _logger.info("DA prices fetched: %d price points", len(da_prices) if da_prices is not None else 0)

                if da_prices is not None:
                    await self._process_available_prices(
                        da_prices, unprocessed_contracts
                    )

                return

            except Exception as exc:  # pylint: disable=broad-exception-caught
                attempt += 1
                _logger.warning(
                    "Connectivity issue detected (attempt %d/%d): %s",
                    attempt,
                    self._config.retries,
                    exc,
                )

                if attempt < self._config.retries:
                    _logger.info("Retrying in %s", backoff)
                    await asyncio.sleep(backoff.total_seconds())
                    backoff *= 2

        _logger.error(
            "Failed to process %d contracts after %d connectivity retry attempts",
            len(unprocessed_contracts),
            self._config.retries,
        )

    def _get_unprocessed_contracts(self) -> list[pd.Timestamp]:
        """Get contracts that haven't been processed yet."""
        return [ts for ts, processed in self._active_contracts.items() if not processed]

    async def _process_available_prices(
        self, da_prices: pd.Series, contracts: list[pd.Timestamp]  # type: ignore[type-arg]
    ) -> None:
        """Process contracts that have available price data."""
        limited_price_count = 0

        for timestamp in contracts:
            if timestamp in da_prices.index:
                price = da_prices[timestamp]

                if price > self._config.price_limit:
                    dispatch_success = await self._send_dispatch(timestamp)
                    if dispatch_success:
                        limited_price_count += 1
                    else:
                        # Don't mark as processed if dispatch failed
                        continue

                self._active_contracts[timestamp] = True

        if limited_price_count > 0:
            _logger.info(
                "Found %d prices above limit %.2f, sent charge curtailment dispatch contracts",
                limited_price_count,
                self._config.price_limit,
            )

    async def _fetch_da_prices(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.Series | None:  # type: ignore[type-arg]
        """Fetch day ahead prices for the given time range.

        Args:
            start: The start timestamp for the price query.
            end: The end timestamp for the price query.

        Returns:
            pd.Series | None: Day ahead prices as a pandas Series, or None if no data available.

        Raises:
            Exception: Any connectivity or other issues that should trigger retries upstream.
        """
        try:
            da_prices: pd.Series = await asyncio.to_thread(  # type: ignore[type-arg]
                self._list_day_ahead_prices,
                start,
                end,
                self._config.country_code,
            )
            return da_prices
        except NoMatchingDataError as exc:
            _logger.info(
                "No day ahead prices available for %s to %s: %s", start, end, exc
            )
            return None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _logger.error("Error fetching day ahead prices: %s", exc)
            _logger.error("Restarting Entsoe client.")
            self._client = EntsoePandasClient(api_key=self._entsoe_key)
            raise

    def _list_day_ahead_prices(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        country_code: str,
    ) -> pd.Series:  # type: ignore[type-arg]
        """
        List day-ahead prices for a given country code.

        Args:
            start: The start date of the query
            end: The end date of the query
            country_code: The country code for which to query the prices

        Returns:
            pd.Series: Day ahead prices as a pandas Series with timestamps as index.
        """
        da_prices = cast(
            pd.Series,  # type: ignore[type-arg]
            self._client.query_day_ahead_prices(country_code, start=start, end=end),
        )
        da_prices.name = "da_price"
        da_prices.index.name = "timestamp"
        return da_prices

    async def _send_dispatch(self, timestamp: pd.Timestamp) -> bool:
        """Send dispatch to curtail charging for the given timestamp.

        Args:
            timestamp: The timestamp for which to send the charge curtailment dispatch.

        Returns:
            bool: True if dispatch was successful for all microgrids, False otherwise.
        """
        _logger.info(
            "Sending charge curtailment dispatch for timestamp %s to %d microgrids",
            timestamp,
            len(self._config.microgrid_ids),
        )

        success_count = 0
        for microgrid_id in self._config.microgrid_ids:
            try:
                await self._dispatch_client.create(
                    microgrid_id=MicrogridId(microgrid_id),
                    type="SE_TRUCK_CHARGING",
                    start_time=timestamp,
                    duration=pd.Timedelta(self._config.da_price_frequency),
                    target=TargetCategories(ComponentCategory.GRID),
                    dry_run=self._dry_run,
                    payload={"power_reduction_w": self._config.power_reduction_w},
                )
                _logger.debug(
                    "Successfully sent charge curtailment dispatch for microgrid %d at %s",
                    microgrid_id,
                    timestamp,
                )
                success_count += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                _logger.error(
                    "Failed to send charge curtailment dispatch for microgrid %d at %s: %s",
                    microgrid_id,
                    timestamp,
                    e,
                )

        # Return True only if all microgrids were processed successfully
        return success_count == len(self._config.microgrid_ids)
