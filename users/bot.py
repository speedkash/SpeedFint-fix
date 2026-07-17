"""
Bots de market making multi-niveaux pour animer le marché FIX.
"""

import random
import time
import threading
from typing import Optional, Callable
from users.user import User
from core.order import OrderSide, OrderType


class MarketMakerBot:
    """
    Bot market maker multi-niveaux.

    Place N ordres d'achat ET N ordres de vente à des prix échelonnés
    autour du dernier prix, créant un vrai carnet profond.
    """

    def __init__(self, user: User, spread_pct: float = 5.0,
                 interval_seconds: float = 10.0,
                 min_qty: int = 1000, max_qty: int = 5000,
                 levels: int = 5):
        self.user = user
        self.user.is_bot = True
        self.spread_pct = spread_pct
        self.interval = interval_seconds
        self.min_qty = min_qty
        self.max_qty = max_qty
        self.levels = levels

        self.running = False
        self.thread: Optional[threading.Thread] = None

        self.get_last_price: Optional[Callable] = None
        self.place_order: Optional[Callable] = None
        self.cancel_all_orders: Optional[Callable] = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print(f"[Bot] {self.user.username} démarré "
              f"({self.levels} niveaux, spread={self.spread_pct}%, interval={self.interval}s)")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print(f"[Bot] {self.user.username} arrêté")

    def _loop(self):
        while self.running:
            try:
                self._cancel_my_orders()
                time.sleep(0.5)
                self._place_orders()
            except Exception as e:
                print(f"[Bot] {self.user.username} erreur : {e}")
            time.sleep(self.interval)

    def _cancel_my_orders(self):
        if self.cancel_all_orders:
            try:
                self.cancel_all_orders(self.user.user_id)
            except Exception as e:
                print(f"[Bot] {self.user.username} erreur annulation : {e}")

    def _place_orders(self):
        if not self.get_last_price or not self.place_order:
            return

        last_price = self.get_last_price() or 0.001
        portfolio = self.user.portfolio

        # --- ORDRES D'ACHAT (en dessous du prix) ---
        for level in range(1, self.levels + 1):
            discount = self.spread_pct * (level / self.levels) / 100
            buy_price = round(last_price * (1 - discount), 6)
            if buy_price <= 0:
                buy_price = 0.000001

            # Vérifier combien on peut acheter avec le cash dispo
            max_affordable = int(portfolio.available_cash / buy_price) if portfolio.available_cash > 0 else 0
            if max_affordable < self.min_qty:
                continue

            buy_qty = random.randint(self.min_qty, min(self.max_qty, max_affordable))

            try:
                self.place_order(
                    user_id=self.user.user_id,
                    username=self.user.username,
                    side=OrderSide.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=buy_qty,
                    price=buy_price
                )
            except Exception:
                pass

        # --- ORDRES DE VENTE (au-dessus du prix) ---
        for level in range(1, self.levels + 1):
            premium = self.spread_pct * (level / self.levels) / 100
            sell_price = round(last_price * (1 + premium), 6)

            # Vérifier combien on peut vendre
            available_fix = portfolio.available_asset("FIX")
            if available_fix < self.min_qty:
                continue

            sell_qty = random.randint(self.min_qty, min(self.max_qty, available_fix))

            try:
                self.place_order(
                    user_id=self.user.user_id,
                    username=self.user.username,
                    side=OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=sell_qty,
                    price=sell_price
                )
            except Exception:
                pass

    def __repr__(self):
        return f"MarketMakerBot({self.user.username}, levels={self.levels})"
