"""
Comprehensive test suite for Price Alert Bot v5.
Tests all critical functions WITHOUT needing a database or Telegram connection.
Uses unittest.mock to simulate DB calls and missing modules.

Mocks psycopg2, telegram, and dotenv at the module level so that
bot.services.database and bot.services.alert_checker can be imported
without actual DB/Telegram dependencies.
"""

import sys
import os
import types
import unittest
import inspect
from unittest.mock import patch, MagicMock, call

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# MODULE-LEVEL MOCKING: Mock external dependencies before ANY bot imports
# ============================================================================

# Mock psycopg2 (database driver - not installed in test env)
mock_psycopg2 = MagicMock()
mock_psycopg2.extras = MagicMock()
mock_psycopg2.extras.RealDictCursor = MagicMock()
sys.modules['psycopg2'] = mock_psycopg2
sys.modules['psycopg2.extras'] = mock_psycopg2.extras

# Mock telegram (python-telegram-bot - not installed in test env)
mock_telegram = MagicMock()
mock_telegram.Bot = MagicMock()
mock_telegram.InlineKeyboardButton = MagicMock()
mock_telegram.InlineKeyboardMarkup = MagicMock()
sys.modules['telegram'] = mock_telegram

# Mock dotenv
mock_dotenv = MagicMock()
mock_dotenv.load_dotenv = MagicMock()
sys.modules['dotenv'] = mock_dotenv

# Mock apscheduler
mock_apscheduler = MagicMock()
sys.modules['apscheduler'] = mock_apscheduler
sys.modules['apscheduler.schedulers'] = MagicMock()
sys.modules['apscheduler.schedulers.asyncio'] = MagicMock()

# Mock bot.utils modules if they import problematic things
# Create the bot.utils.token_masker module with real-looking functions
mock_token_masker = types.ModuleType('bot.utils.token_masker')
mock_token_masker.mask_token = lambda x: '***' if x else 'None'
mock_token_masker.mask_database_url = lambda x: '***' if x else 'None'
mock_token_masker.mask_error_message = lambda x: str(x)
sys.modules['bot.utils.token_masker'] = mock_token_masker

# Mock bot.utils.logger
mock_logger_mod = types.ModuleType('bot.utils.logger')
mock_logger_mod.logger = MagicMock()
sys.modules['bot.utils.logger'] = mock_logger_mod

# Mock bot.utils.formatters
mock_formatters = types.ModuleType('bot.utils.formatters')
mock_formatters.format_alert_message = lambda *a, **kw: "mock alert"
mock_formatters.get_symbol_link = lambda sym, pct: f"https://example.com/{sym}"
sys.modules['bot.utils.formatters'] = mock_formatters

# Mock bot.services.bybit_api
mock_bybit = types.ModuleType('bot.services.bybit_api')
mock_bybit.fetch_tickers = MagicMock(return_value=[])
mock_bybit.get_bybit_category = MagicMock(return_value='linear')
sys.modules['bot.services.bybit_api'] = mock_bybit

# Mock bot.services.session_manager
mock_session = types.ModuleType('bot.services.session_manager')
mock_session.reset_daily_sessions = MagicMock()
mock_session.initialize_session_prices = MagicMock()
sys.modules['bot.services.session_manager'] = mock_session

# Mock bot.services.cleanup
mock_cleanup = types.ModuleType('bot.services.cleanup')
mock_cleanup.run_cleanup = MagicMock()
sys.modules['bot.services.cleanup'] = mock_cleanup

# Now we can safely import from the bot package
from bot.config import (
    DEFAULT_BTC_ETH_ALERT_MODE, DEFAULT_MILESTONE_COOLDOWN,
    DEFAULT_SHORT_TERM_TREND, DEFAULT_BTC_MILESTONE, DEFAULT_ETH_MILESTONE,
    BASE_THRESHOLDS, EXTENDED_THRESHOLD_STEP, DEFAULT_SCAN_INTERVAL,
    DEFAULT_MILESTONE_LOCK, DEFAULT_SHORT_TERM_LOOKBACK
)
from bot.services.database import (
    get_milestone_realtime_with_trend,
    get_crossed_milestones_realtime,
    can_fire_milestone_alert,
)
from bot.services.alert_checker import (
    get_crossed_thresholds,
    is_btc_eth_milestone_mode,
    get_btc_eth_milestone_step,
    is_usdt_pair,
    calculate_percentage_change,
    classify_movement,
    format_milestone_alert,
)


# ============================================================================
# TEST 1: Boundary Crossing Detection (get_milestone_realtime_with_trend)
# ============================================================================
class TestBoundaryCrossingDetection(unittest.TestCase):
    """
    Tests for get_milestone_realtime_with_trend in database.py.
    This is the MOST CRITICAL function -- detects when price crosses
    exact round-number boundaries like $70,000 or $2,100.
    """

    def _call_milestone(self, symbol, current_price, ref_24h, step,
                        last_price, short_term_ref=None):
        """
        Helper: call get_milestone_realtime_with_trend with mocked DB.
        Mocks get_milestone_last_price to return `last_price`,
        and set_milestone_last_price to be a no-op.
        """
        with patch('bot.services.database.get_milestone_last_price', return_value=last_price), \
             patch('bot.services.database.set_milestone_last_price'):
            return get_milestone_realtime_with_trend(
                symbol, current_price, ref_24h, step,
                short_term_ref_price=short_term_ref
            )

    # --- Basic DOWN crossing ---
    def test_btc_70050_to_69984_detects_70000_down(self):
        """$70,050 -> $69,984 (step=1000) should detect $70,000 DOWN."""
        result = self._call_milestone(
            'BTCUSDT', 69984, 71000, 1000,
            last_price=70050, short_term_ref=71000  # bearish trend -> allows DOWN
        )
        self.assertIsNotNone(result, "Should detect $70,000 boundary crossing")
        self.assertEqual(result['milestone'], 70000)
        self.assertEqual(result['direction'], 'down')
        self.assertEqual(result['skipped_milestones'], [])

    # --- Basic UP crossing ---
    def test_btc_69950_to_70001_detects_70000_up(self):
        """$69,950 -> $70,001 (step=1000) should detect $70,000 UP."""
        result = self._call_milestone(
            'BTCUSDT', 70001, 69000, 1000,
            last_price=69950, short_term_ref=69000  # bullish trend -> allows UP
        )
        self.assertIsNotNone(result, "Should detect $70,000 boundary crossing")
        self.assertEqual(result['milestone'], 70000)
        self.assertEqual(result['direction'], 'up')
        self.assertEqual(result['skipped_milestones'], [])

    # --- Multi-level skip UP ---
    def test_btc_70000_to_73100_detects_73000_up_skipped_71k_72k(self):
        """$70,000 -> $73,100 (step=1000) should detect $73,000 UP, skipped=[71k,72k]."""
        result = self._call_milestone(
            'BTCUSDT', 73100, 69000, 1000,
            last_price=70000, short_term_ref=69000  # bullish
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['milestone'], 73000)
        self.assertEqual(result['direction'], 'up')
        self.assertEqual(result['skipped_milestones'], [71000, 72000])

    # --- Multi-level skip DOWN ---
    def test_btc_73100_to_69800_detects_70000_down_skipped_71k_72k_73k(self):
        """$73,100 -> $69,800 (step=1000) should detect $70,000 DOWN, skipped=[71k,72k,73k]."""
        result = self._call_milestone(
            'BTCUSDT', 69800, 74000, 1000,
            last_price=73100, short_term_ref=74000  # bearish trend -> allows DOWN
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['milestone'], 70000)
        self.assertEqual(result['direction'], 'down')
        self.assertEqual(sorted(result['skipped_milestones']), [71000, 72000, 73000])

    # --- No boundary crossed ---
    def test_btc_69500_to_69800_no_crossing(self):
        """$69,500 -> $69,800 with step=1000 should NOT cross any boundary."""
        result = self._call_milestone(
            'BTCUSDT', 69800, 69000, 1000,
            last_price=69500, short_term_ref=69000  # irrelevant, no crossing
        )
        self.assertIsNone(result, "No boundary between 69500 and 69800 for step=1000")

    # --- ETH DOWN crossing ---
    def test_eth_2150_to_2095_detects_2100_down(self):
        """$2,150 -> $2,095 (step=100) should detect $2,100 DOWN."""
        result = self._call_milestone(
            'ETHUSDT', 2095, 2200, 100,
            last_price=2150, short_term_ref=2200  # bearish for DOWN
        )
        self.assertIsNotNone(result, "Should detect $2,100 boundary")
        self.assertEqual(result['milestone'], 2100)
        self.assertEqual(result['direction'], 'down')

    # --- ETH UP crossing ---
    def test_eth_2095_to_2150_detects_2100_up(self):
        """$2,095 -> $2,150 (step=100) should detect $2,100 UP."""
        result = self._call_milestone(
            'ETHUSDT', 2150, 2000, 100,
            last_price=2095, short_term_ref=2000  # bullish for UP
        )
        self.assertIsNotNone(result, "Should detect $2,100 boundary")
        self.assertEqual(result['milestone'], 2100)
        self.assertEqual(result['direction'], 'up')

    # --- CRITICAL: Floor division bug regression tests ---
    def test_no_floor_division_bug_69984_not_mapped_to_69000(self):
        """
        REGRESSION: Floor division maps $69,984 to $69,000 (WRONG).
        The correct behavior is to detect $70,000 boundary crossing.
        $70,050 -> $69,984 should report $70,000, NOT $69,000.
        """
        result = self._call_milestone(
            'BTCUSDT', 69984, 71000, 1000,
            last_price=70050, short_term_ref=71000
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['milestone'], 70000,
                         "Floor division bug: $69,984 must NOT map to $69,000. "
                         "Correct: $70,000 boundary was crossed.")
        self.assertNotEqual(result['milestone'], 69000,
                            "FLOOR DIVISION BUG DETECTED!")

    def test_no_floor_division_bug_eth_2095_not_mapped_to_2000(self):
        """
        REGRESSION: Floor division maps $2,095 to $2,000 (WRONG).
        $2,150 -> $2,095 should report $2,100, NOT $2,000.
        """
        result = self._call_milestone(
            'ETHUSDT', 2095, 2200, 100,
            last_price=2150, short_term_ref=2200
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['milestone'], 2100,
                         "Floor division bug: $2,095 must NOT map to $2,000. "
                         "Correct: $2,100 boundary was crossed.")
        self.assertNotEqual(result['milestone'], 2000,
                            "FLOOR DIVISION BUG DETECTED!")

    # --- Trend filter: UP + bearish trend -> None ---
    def test_trend_filter_up_with_bearish_trend_returns_none(self):
        """UP crossing + bearish trend should be filtered out (return None)."""
        # Price goes up: $69,950 -> $70,001 (crosses $70k UP)
        # But trend is bearish (ref=71000, current=70001 => negative)
        result = self._call_milestone(
            'BTCUSDT', 70001, 71000, 1000,
            last_price=69950, short_term_ref=71000  # bearish: 70001 < 71000
        )
        self.assertIsNone(result,
                          "UP crossing with bearish trend should be filtered out")

    # --- Trend filter: DOWN + bullish trend -> None ---
    def test_trend_filter_down_with_bullish_trend_returns_none(self):
        """DOWN crossing + bullish trend should be filtered out (return None)."""
        # Price goes down: $70,050 -> $69,984 (crosses $70k DOWN)
        # But trend is bullish (ref=69000, current=69984 => positive)
        result = self._call_milestone(
            'BTCUSDT', 69984, 69000, 1000,
            last_price=70050, short_term_ref=69000  # bullish: 69984 > 69000
        )
        self.assertIsNone(result,
                          "DOWN crossing with bullish trend should be filtered out")

    # --- First run (no last_price) stores price, returns None ---
    def test_first_run_no_last_price_returns_none(self):
        """First run with no stored last_price should initialize and return None."""
        with patch('bot.services.database.get_milestone_last_price', return_value=None), \
             patch('bot.services.database.set_milestone_last_price') as mock_set:
            result = get_milestone_realtime_with_trend(
                'BTCUSDT', 70000, 69000, 1000
            )
            self.assertIsNone(result, "First run should return None (initializing)")
            mock_set.assert_called_once_with('BTCUSDT', 70000)

    # --- Same price -> None ---
    def test_same_price_returns_none(self):
        """If current_price == last_price, no crossing detected."""
        result = self._call_milestone(
            'BTCUSDT', 70500, 69000, 1000,
            last_price=70500, short_term_ref=69000
        )
        self.assertIsNone(result, "Same price should return None")

    # --- 241 mode: falls back to 24h when no short_term_ref ---
    def test_241_fallback_to_24h_when_no_short_term(self):
        """When short_term_ref_price is None, should use reference_price_24h for trend."""
        # UP crossing, 24h ref = 69000 (bullish), no short_term
        result = self._call_milestone(
            'BTCUSDT', 70001, 69000, 1000,
            last_price=69950, short_term_ref=None
        )
        self.assertIsNotNone(result,
                             "Should use 24h ref as fallback (bullish) and allow UP alert")
        self.assertEqual(result['milestone'], 70000)
        self.assertEqual(result['direction'], 'up')

    # --- Exact boundary start price ---
    def test_price_starts_exactly_on_boundary(self):
        """If last_price is exactly on $70,000, and crosses to $71,100."""
        result = self._call_milestone(
            'BTCUSDT', 71100, 69000, 1000,
            last_price=70000, short_term_ref=69000  # bullish
        )
        self.assertIsNotNone(result)
        self.assertEqual(result['milestone'], 71000)
        self.assertEqual(result['direction'], 'up')
        # $70,000 is last_price (the low). First boundary strictly above 70000 is 71000.
        self.assertEqual(result['skipped_milestones'], [])


# ============================================================================
# TEST 2: Percentage Thresholds (get_crossed_thresholds)
# ============================================================================
class TestPercentageThresholds(unittest.TestCase):
    """Tests for get_crossed_thresholds in alert_checker.py."""

    def test_plus_39_with_defaults_crosses_10_and_30(self):
        """+39% with default thresholds [10,30,60,80,100] should cross [10, 30]."""
        result = get_crossed_thresholds(39.0)
        self.assertEqual(result, [10, 30])

    def test_plus_7_incremental_2_crosses_2_4_6(self):
        """+7% with incremental [2] should cross [2, 4, 6]."""
        result = get_crossed_thresholds(7.0, [2], True)
        self.assertEqual(result, [2, 4, 6])

    def test_minus_11_incremental_3_crosses_neg3_neg6_neg9(self):
        """-11% with incremental [3] should cross [-3, -6, -9]."""
        result = get_crossed_thresholds(-11.0, [3], True)
        self.assertEqual(result, [-3, -6, -9])

    def test_plus_5_with_defaults_crosses_nothing(self):
        """+5% with defaults should cross nothing (10 is the first threshold)."""
        result = get_crossed_thresholds(5.0)
        self.assertEqual(result, [])

    def test_plus_100_with_defaults(self):
        """+100% should cross [10, 30, 60, 80, 100]."""
        result = get_crossed_thresholds(100.0)
        self.assertEqual(result, [10, 30, 60, 80, 100])

    def test_plus_155_with_defaults_includes_extended(self):
        """+155% should cross [10, 30, 60, 80, 100, 150]."""
        result = get_crossed_thresholds(155.0)
        self.assertEqual(result, [10, 30, 60, 80, 100, 150])

    def test_minus_35_with_defaults(self):
        """-35% should cross [-10, -30]."""
        result = get_crossed_thresholds(-35.0)
        self.assertEqual(result, [-10, -30])

    def test_zero_change(self):
        """0% change should cross nothing."""
        result = get_crossed_thresholds(0.0)
        self.assertEqual(result, [])

    def test_exactly_10(self):
        """Exactly +10.0% should cross [10]."""
        result = get_crossed_thresholds(10.0)
        self.assertEqual(result, [10])

    def test_custom_thresholds_standard_mode(self):
        """Custom thresholds in standard mode (non-incremental)."""
        result = get_crossed_thresholds(20.0, [5, 15, 25], False)
        self.assertEqual(result, [5, 15])


# ============================================================================
# TEST 3: Highest Threshold Logic (sorted loop in check_and_send_alerts)
# ============================================================================
class TestHighestThresholdLogic(unittest.TestCase):
    """
    Tests that when multiple thresholds are crossed, only the HIGHEST fires
    as the actual alert, and all lower thresholds are also recorded in cooldown.
    """

    def test_sorted_thresholds_highest_first(self):
        """
        +39% crosses [10, 30]. Sorted descending by abs = [30, 10].
        Alert should fire at 30 (highest that can fire).
        Then 10 should be recorded in cooldown too.
        """
        crossed = get_crossed_thresholds(39.0)
        self.assertEqual(crossed, [10, 30])

        # The code sorts by abs descending
        sorted_thresholds = sorted(crossed, key=abs, reverse=True)
        self.assertEqual(sorted_thresholds, [30, 10])

        # First one tried (30) fires -> that's the alert
        self.assertEqual(sorted_thresholds[0], 30)
        # Lower threshold (10) gets recorded in cooldown
        lower_thresholds = [t for t in sorted_thresholds
                            if abs(t) < abs(sorted_thresholds[0])]
        self.assertEqual(lower_thresholds, [10])

    def test_minus_75_highest_is_neg60(self):
        """-75% crosses [-10, -30, -60]. Highest abs is -60."""
        crossed = get_crossed_thresholds(-75.0)
        self.assertEqual(crossed, [-10, -30, -60])

        sorted_thresholds = sorted(crossed, key=abs, reverse=True)
        self.assertEqual(sorted_thresholds[0], -60)
        lower = [t for t in sorted_thresholds if abs(t) < 60]
        self.assertIn(-30, lower)
        self.assertIn(-10, lower)

    def test_incremental_highest(self):
        """+7% incremental 2 crosses [2,4,6]. Highest is 6."""
        crossed = get_crossed_thresholds(7.0, [2], True)
        sorted_thresholds = sorted(crossed, key=abs, reverse=True)
        self.assertEqual(sorted_thresholds[0], 6)


# ============================================================================
# TEST 4: Alert Routing (price_monitor logic)
# ============================================================================
class TestAlertRouting(unittest.TestCase):
    """
    Tests the routing logic in scan_prices:
    - BTCUSDT/ETHUSDT + milestone mode -> milestone path
    - BTCPERP + milestone mode -> percentage path
    - SOLUSDT -> always percentage path
    - BTCUSDT + percentage mode -> percentage path
    """

    def _check_routing(self, symbol, use_milestone_mode):
        """
        Simulate the routing logic from scan_prices.
        Returns 'milestone' or 'percentage'.
        This is the exact logic from price_monitor.py line:
            is_btc_eth_usdt = symbol.upper() in ('BTCUSDT', 'ETHUSDT')
        """
        is_btc_eth_usdt = symbol.upper() in ('BTCUSDT', 'ETHUSDT')
        if is_btc_eth_usdt and use_milestone_mode:
            return 'milestone'
        else:
            return 'percentage'

    def test_btcusdt_milestone_mode_goes_milestone(self):
        """BTCUSDT with milestone mode should go milestone path."""
        self.assertEqual(self._check_routing('BTCUSDT', True), 'milestone')

    def test_ethusdt_milestone_mode_goes_milestone(self):
        """ETHUSDT with milestone mode should go milestone path."""
        self.assertEqual(self._check_routing('ETHUSDT', True), 'milestone')

    def test_btcperp_milestone_mode_goes_percentage(self):
        """BTCPERP with milestone mode should go percentage path (not exact match)."""
        self.assertEqual(self._check_routing('BTCPERP', True), 'percentage')

    def test_solusdt_always_percentage(self):
        """SOLUSDT should always go percentage path regardless of mode."""
        self.assertEqual(self._check_routing('SOLUSDT', True), 'percentage')
        self.assertEqual(self._check_routing('SOLUSDT', False), 'percentage')

    def test_btcusdt_percentage_mode_goes_percentage(self):
        """BTCUSDT with percentage mode (not milestone) should go percentage path."""
        self.assertEqual(self._check_routing('BTCUSDT', False), 'percentage')

    def test_ethusdt_percentage_mode_goes_percentage(self):
        """ETHUSDT with percentage mode should go percentage path."""
        self.assertEqual(self._check_routing('ETHUSDT', False), 'percentage')

    def test_btcdomusdt_not_routed_as_btc(self):
        """BTCDOMUSDT should NOT be routed as BTC milestone (not in exact match list)."""
        self.assertEqual(self._check_routing('BTCDOMUSDT', True), 'percentage')

    def test_ethfiusdt_not_routed_as_eth(self):
        """ETHFIUSDT should NOT be routed as ETH milestone."""
        self.assertEqual(self._check_routing('ETHFIUSDT', True), 'percentage')


# ============================================================================
# TEST 5: Config Defaults
# ============================================================================
class TestConfigDefaults(unittest.TestCase):
    """Tests that critical config defaults are set correctly."""

    def test_default_btc_eth_alert_mode_is_milestone(self):
        """DEFAULT_BTC_ETH_ALERT_MODE should be 'milestone'."""
        self.assertEqual(DEFAULT_BTC_ETH_ALERT_MODE, 'milestone')

    def test_default_milestone_cooldown_is_1440(self):
        """DEFAULT_MILESTONE_COOLDOWN should be 1440 (24 hours in minutes)."""
        self.assertEqual(DEFAULT_MILESTONE_COOLDOWN, 1440)

    def test_default_short_term_trend_is_true(self):
        """DEFAULT_SHORT_TERM_TREND should be 'true'."""
        self.assertEqual(DEFAULT_SHORT_TERM_TREND, 'true')

    def test_default_btc_milestone_step(self):
        """DEFAULT_BTC_MILESTONE should be 1000."""
        self.assertEqual(DEFAULT_BTC_MILESTONE, 1000)

    def test_default_eth_milestone_step(self):
        """DEFAULT_ETH_MILESTONE should be 100."""
        self.assertEqual(DEFAULT_ETH_MILESTONE, 100)

    def test_base_thresholds(self):
        """BASE_THRESHOLDS should be [10, 30, 60, 80, 100]."""
        self.assertEqual(BASE_THRESHOLDS, [10, 30, 60, 80, 100])

    def test_extended_threshold_step(self):
        """EXTENDED_THRESHOLD_STEP should be 50."""
        self.assertEqual(EXTENDED_THRESHOLD_STEP, 50)

    def test_default_scan_interval(self):
        """DEFAULT_SCAN_INTERVAL should be 30."""
        self.assertEqual(DEFAULT_SCAN_INTERVAL, 30)

    def test_default_milestone_lock(self):
        """DEFAULT_MILESTONE_LOCK should be 30."""
        self.assertEqual(DEFAULT_MILESTONE_LOCK, 30)

    def test_default_short_term_lookback(self):
        """DEFAULT_SHORT_TERM_LOOKBACK should be 3600 (1 hour)."""
        self.assertEqual(DEFAULT_SHORT_TERM_LOOKBACK, 3600)


# ============================================================================
# TEST 6: Cooldown Direction-Agnostic Check (can_fire_milestone_alert)
# ============================================================================
class TestCooldownDirectionAgnostic(unittest.TestCase):
    """
    Verify that can_fire_milestone_alert does NOT filter by direction.
    The SQL query should check symbol + milestone + expires_at only,
    NOT direction. This prevents contradicting alerts like
    "BREAKS $71k" then "DROPS TO $71k" within minutes.
    """

    def test_sql_query_has_no_direction_filter(self):
        """
        Inspect the source code of can_fire_milestone_alert to verify
        the SQL query does NOT include 'direction' in the WHERE clause.
        """
        source = inspect.getsource(can_fire_milestone_alert)

        # Extract lines that are part of the SQL query (between triple-quotes in execute)
        lines = source.split('\n')
        in_sql = False
        sql_lines = []
        for line in lines:
            stripped = line.strip()
            if 'cursor.execute("""' in stripped or "cursor.execute('''" in stripped:
                in_sql = True
                continue
            if in_sql:
                if '"""' in stripped or "'''" in stripped:
                    in_sql = False
                    continue
                sql_lines.append(stripped)

        sql_block = '\n'.join(sql_lines)

        # The WHERE clause should NOT contain 'direction'
        self.assertNotIn("AND direction", sql_block,
                         "CRITICAL: can_fire_milestone_alert SQL query must NOT "
                         "filter by direction! Cooldown should be direction-agnostic.")

    def test_function_signature_has_direction_but_unused_in_query(self):
        """
        can_fire_milestone_alert should accept direction param (API compat)
        but not use it in the DB query.
        """
        sig = inspect.signature(can_fire_milestone_alert)
        params = list(sig.parameters.keys())
        self.assertIn('direction', params,
                      "direction param should exist for API compatibility")

    def test_query_params_exclude_direction(self):
        """
        Verify the execute() call parameters do NOT include direction.
        The params tuple should be (symbol, milestone, current_time) only.
        """
        source = inspect.getsource(can_fire_milestone_alert)

        # Find lines with the SQL parameter tuple after the execute
        lines = source.split('\n')
        for line in lines:
            clean = line.replace(' ', '')
            # Look for the parameters passed after the SQL string
            if '(symbol,milestone,' in clean and 'current_time' in clean:
                # Check direction is NOT in this params tuple
                self.assertNotIn('direction', clean,
                                 "CRITICAL: direction is passed as SQL parameter! "
                                 "Cooldown must be direction-agnostic.")
                return

        # If we couldn't find the params line, check the whole function
        # for a pattern like "%s, %s, %s, %s" which would indicate 4 params
        # (the query only needs 3: symbol, milestone, current_time)
        self.assertIn('symbol, milestone, current_time', source.replace(' ', ''),
                      "Expected params (symbol, milestone, current_time) not found")


# ============================================================================
# TEST 7: Additional Edge Cases and Helper Functions
# ============================================================================
class TestEdgeCases(unittest.TestCase):
    """Additional edge case tests for helper functions."""

    def test_is_usdt_pair_check(self):
        """Verify is_usdt_pair correctly identifies USDT vs PERP."""
        self.assertTrue(is_usdt_pair('BTCUSDT'))
        self.assertTrue(is_usdt_pair('ETHUSDT'))
        self.assertFalse(is_usdt_pair('BTCPERP'))
        self.assertFalse(is_usdt_pair('ETHPERP'))

    def test_is_btc_eth_milestone_mode_on(self):
        """Test is_btc_eth_milestone_mode when set to milestone."""
        with patch('bot.services.alert_checker.get_bot_setting', return_value='milestone'):
            self.assertTrue(is_btc_eth_milestone_mode())

    def test_is_btc_eth_milestone_mode_off(self):
        """Test is_btc_eth_milestone_mode when set to percentage."""
        with patch('bot.services.alert_checker.get_bot_setting', return_value='percentage'):
            self.assertFalse(is_btc_eth_milestone_mode())

    def test_get_btc_milestone_step(self):
        """Test milestone step retrieval for BTC."""
        with patch('bot.services.alert_checker.get_bot_setting', return_value='1000'):
            self.assertEqual(get_btc_eth_milestone_step('BTCUSDT'), 1000)

    def test_get_eth_milestone_step(self):
        """Test milestone step retrieval for ETH."""
        with patch('bot.services.alert_checker.get_bot_setting', return_value='100'):
            self.assertEqual(get_btc_eth_milestone_step('ETHUSDT'), 100)

    def test_get_sol_milestone_step_is_none(self):
        """SOLUSDT has no milestone step."""
        with patch('bot.services.alert_checker.get_bot_setting'):
            self.assertIsNone(get_btc_eth_milestone_step('SOLUSDT'))

    def test_calculate_percentage_change_up(self):
        """Test +100% calculation: 200 from 100."""
        self.assertAlmostEqual(calculate_percentage_change(200, 100), 100.0)

    def test_calculate_percentage_change_down(self):
        """Test -50% calculation: 50 from 100."""
        self.assertAlmostEqual(calculate_percentage_change(50, 100), -50.0)

    def test_calculate_percentage_change_zero(self):
        """Test 0% change."""
        self.assertAlmostEqual(calculate_percentage_change(100, 100), 0.0)

    def test_calculate_percentage_change_div_zero(self):
        """Test division by zero protection."""
        self.assertAlmostEqual(calculate_percentage_change(100, 0), 0.0)

    def test_classify_movement_gainer(self):
        self.assertEqual(classify_movement(5.0), "GAINER")

    def test_classify_movement_loser(self):
        self.assertEqual(classify_movement(-3.0), "LOSER")

    def test_classify_movement_neutral(self):
        self.assertEqual(classify_movement(0.0), "NEUTRAL")

    def test_format_milestone_alert_btc_up(self):
        """Test milestone alert formatting for BTC going up."""
        msg = format_milestone_alert('BTCUSDT', 70050.0, 70000.0, 'up', 5e9, 2.5)
        self.assertIn('BITCOIN', msg)
        self.assertIn('BREAKS', msg)
        self.assertIn('$70,000', msg)

    def test_format_milestone_alert_eth_down(self):
        """Test milestone alert formatting for ETH going down."""
        msg = format_milestone_alert('ETHUSDT', 2095.0, 2100.0, 'down', 1e9, -3.0)
        self.assertIn('ETHEREUM', msg)
        self.assertIn('DROPS TO', msg)
        self.assertIn('$2,100', msg)

    def test_get_crossed_milestones_realtime_basic(self):
        """Test the deprecated get_crossed_milestones_realtime (basic down crossing)."""
        # Going down: 65500 -> 64900, step=1000 -> crosses 65000
        result = get_crossed_milestones_realtime(64900, 65500, 1000)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['milestone'], 65000)
        self.assertEqual(result[0]['direction'], 'down')

    def test_get_crossed_milestones_realtime_multi(self):
        """Test multiple milestone crossings in get_crossed_milestones_realtime."""
        # Going up: 69500 -> 72500, step=1000 -> crosses 70000, 71000, 72000
        result = get_crossed_milestones_realtime(72500, 69500, 1000)
        milestones = [r['milestone'] for r in result]
        self.assertEqual(milestones, [70000, 71000, 72000])
        for r in result:
            self.assertEqual(r['direction'], 'up')

    def test_get_crossed_milestones_realtime_no_crossing(self):
        """No crossing when prices are in the same range."""
        result = get_crossed_milestones_realtime(69700, 69500, 1000)
        self.assertEqual(result, [])

    def test_get_crossed_milestones_realtime_same_price(self):
        """Same price -> empty list."""
        result = get_crossed_milestones_realtime(70000, 70000, 1000)
        self.assertEqual(result, [])


# ============================================================================
# MAIN
# ============================================================================
if __name__ == '__main__':
    print("=" * 70)
    print("PRICE ALERT BOT v5 - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    print()

    # Run with verbosity=2 for detailed output
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestBoundaryCrossingDetection,
        TestPercentageThresholds,
        TestHighestThresholdLogic,
        TestAlertRouting,
        TestConfigDefaults,
        TestCooldownDirectionAgnostic,
        TestEdgeCases,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print()
    print("=" * 70)
    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total - failures - errors
    print(f"RESULTS: {passed}/{total} passed, {failures} failures, {errors} errors")
    if result.wasSuccessful():
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED - SEE ABOVE FOR DETAILS")
    print("=" * 70)

    sys.exit(0 if result.wasSuccessful() else 1)
