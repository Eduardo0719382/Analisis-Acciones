"""Watchlists: named, ordered lists of symbols stored locally."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from analisis_acciones.models.errors import UserError
from analisis_acciones.providers.base import normalize_symbol
from analisis_acciones.services.market_data_service import CSV_PREFIX, is_csv_symbol
from analisis_acciones.storage.watchlist_repository import Watchlist, WatchlistRepository

DEFAULT_LIST_NAME = "Favoritos"
MAX_NAME_LENGTH = 40
MAX_ITEMS = 200


class WatchlistService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = WatchlistRepository(conn)
        self._clock = clock

    # Lists -------------------------------------------------------------------
    def lists(self) -> list[Watchlist]:
        lists = self._repo.lists()
        if not lists:
            lists = [self._repo.create(DEFAULT_LIST_NAME)]
        return lists

    def _valid_name(self, name: str, exclude_id: int | None = None) -> str:
        clean = " ".join(name.split())
        if not clean or len(clean) > MAX_NAME_LENGTH:
            raise UserError(
                f"invalid list name {name!r}",
                user_message=f"El nombre debe tener entre 1 y {MAX_NAME_LENGTH} caracteres.",
            )
        if self._repo.name_exists(clean, exclude_id):
            raise UserError(
                f"duplicate list name {clean!r}",
                user_message=f"Ya existe una lista llamada «{clean}».",
            )
        return clean

    def create(self, name: str) -> Watchlist:
        return self._repo.create(self._valid_name(name))

    def rename(self, list_id: int, name: str) -> None:
        self._require(list_id)
        self._repo.rename(list_id, self._valid_name(name, exclude_id=list_id))

    def delete(self, list_id: int) -> None:
        self._require(list_id)
        if len(self._repo.lists()) <= 1:
            raise UserError(
                "cannot delete the last list",
                user_message="No se puede eliminar la única lista.",
            )
        self._repo.delete(list_id)

    def _require(self, list_id: int) -> Watchlist:
        watchlist = self._repo.get(list_id)
        if watchlist is None:
            raise UserError(f"unknown list {list_id}", user_message="La lista ya no existe.")
        return watchlist

    # Items -------------------------------------------------------------------
    def symbols(self, list_id: int) -> list[str]:
        return self._repo.symbols(list_id)

    def add(self, list_id: int, raw_symbol: str) -> bool:
        self._require(list_id)
        if is_csv_symbol(raw_symbol):
            symbol = CSV_PREFIX + raw_symbol.strip()[len(CSV_PREFIX) :].upper()
        else:
            symbol = normalize_symbol(raw_symbol)
        if len(self._repo.symbols(list_id)) >= MAX_ITEMS:
            raise UserError(
                "watchlist full", user_message=f"Una lista admite como máximo {MAX_ITEMS} activos."
            )
        return self._repo.add(list_id, symbol, self._clock())

    def remove(self, list_id: int, symbol: str) -> None:
        self._repo.remove(list_id, symbol)

    def move(self, list_id: int, symbol: str, offset: int) -> list[str]:
        """Move ``symbol`` up (negative) or down (positive); returns the new order."""
        symbols = self._repo.symbols(list_id)
        if symbol not in symbols:
            return symbols
        index = symbols.index(symbol)
        target = max(0, min(len(symbols) - 1, index + offset))
        if target != index:
            symbols.insert(target, symbols.pop(index))
            self._repo.set_order(list_id, symbols)
        return symbols
