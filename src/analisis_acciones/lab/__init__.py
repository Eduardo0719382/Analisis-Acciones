"""Experiment lab: virtual 100 USD sub-accounts traded by agents on Alpaca PAPER.

The agents (Claude Sonnet in scheduled tasks) decide; this package keeps the books, applies
the costs, enforces each profile's hard limits and sends the orders to the paper account.
Nothing here can reach a real-money account (see ``broker.alpaca.PAPER_URL``).
"""
