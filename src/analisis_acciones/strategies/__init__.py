"""Trading-rule definitions for backtests. Must not import Qt.

A strategy turns bars into entry/exit *signals* evaluated at each bar's close
using only data up to that bar. Execution (when and at what price) belongs to
the backtesting engine, not to the strategy.
"""
