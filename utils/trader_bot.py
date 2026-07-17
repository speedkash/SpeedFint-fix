"""
Bot de trading aléatoire.
S'associe à un compte utilisateur existant et trade avec ses soldes.
Exécute uniquement des ordres MARKET.
"""

import random
import time
import threading
from typing import Optional, Callable


class RandomTraderBot:
    """
    Bot qui trade aléatoirement sur le compte d'un utilisateur.

    Stratégie :
        - Choisit aléatoirement achat ou vente
        - Ordres MARKET uniquement (exécution immédiate)
        - Quantité aléatoire dans la plage configurée
    """

    def __init__(self, username: str, get_user_func: Callable,
                 place_order_func: Callable, get_last_price_func: Callable,
                 interval_seconds: float = 15.0,
                 min_qty: int = 1000, max_qty: int = 5000):
        """
        Args:
            username            : Nom du compte utilisateur à utiliser
            get_user_func       : Fonction qui retourne l'objet User
            place_order_func    : Fonction pour passer un ordre
            get_last_price_func : Fonction qui retourne le dernier prix
            interval_seconds    : Délai entre deux trades
            min_qty, max_qty    : Plage de quantités
        """
        self.username = username
        self.get_user = get_user_func
        self.place_order = place_order_func
        self.get_last_price = get_last_price_func
        self.interval = interval_seconds
        self.min_qty = min_qty
        self.max_qty = max_qty

        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self):
        """Démarre le bot en arrière-plan."""
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print(f"[RandomBot] {self.username} démarré (interval={self.interval}s, MARKET uniquement)")

    def stop(self):
        """Arrête le bot."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print(f"[RandomBot] {self.username} arrêté")

    def _loop(self):
        """Boucle infinie : trade aléatoire."""
        while self.running:
            try:
                self._random_trade()
            except Exception as e:
                print(f"[RandomBot] {self.username} erreur : {e}")
            time.sleep(self.interval)

    def _random_trade(self):
        """Effectue un trade aléatoire (MARKET uniquement)."""
        user = self.get_user(self.username)
        if not user:
            print(f"[RandomBot] {self.username} : utilisateur introuvable")
            return

        portfolio = user.portfolio
        last_price = self.get_last_price() or 0.001

        # --- Décider achat ou vente selon ce qui est disponible ---
        can_buy = portfolio.available_cash > 0
        can_sell = portfolio.available_asset("FIX") >= self.min_qty

        if not can_buy and not can_sell:
            return

        if can_buy and can_sell:
            side = random.choice(["buy", "sell"])
        elif can_buy:
            side = "buy"
        else:
            side = "sell"

        # --- Quantité ---
        if side == "buy":
            max_possible = int(portfolio.available_cash / last_price) if last_price > 0 else 0
            max_qty = min(self.max_qty, max_possible)
        else:
            max_qty = min(self.max_qty, portfolio.available_asset("FIX"))

        if max_qty < self.min_qty:
            return

        qty = random.randint(self.min_qty, max_qty)

        # --- Passer l'ordre MARKET ---
        from core.order import OrderSide, OrderType

        side_enum = OrderSide.BUY if side == "buy" else OrderSide.SELL
        type_enum = OrderType.MARKET

        result = self.place_order(
            user_id=user.user_id,
            username=user.username,
            side=side_enum,
            order_type=type_enum,
            quantity=qty,
            price=None
        )

        if result and result.get("success"):
            trades = result.get("trades", [])
            if trades:
                total_qty = sum(t.get("quantity", 0) for t in trades)
                avg_price = sum(t.get("price", 0) * t.get("quantity", 0) for t in trades) / total_qty if total_qty > 0 else 0
                print(f"[RandomBot] {self.username} : {side} MARKET "
                      f"{total_qty}/{qty} FIX @ ~{avg_price:.6f} → "
                      f"{len(trades)} trade(s)")
            else:
                print(f"[RandomBot] {self.username} : {side} MARKET "
                      f"{qty} FIX → aucune contrepartie")
        else:
            error = result.get("error", "?") if result else "?"
            print(f"[RandomBot] {self.username} : échec - {error}")

    def __repr__(self):
        return f"RandomTraderBot({self.username}, MARKET only)"
