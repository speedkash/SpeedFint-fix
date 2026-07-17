"""
Moteur d'appariement : fait matcher les ordres d'achat et de vente.
Cœur du marché FIX.
"""

from datetime import datetime
from typing import List, Optional, Callable
from .order import Order, OrderSide, OrderType, OrderStatus
from .orderbook import OrderBook
from .exceptions import InsufficientFundsError, InsufficientAssetsError


class Trade:
    """
    Représente une transaction exécutée.
    """

    def __init__(self, buy_order: Order, sell_order: Order,
                 price: float, quantity: int):
        self.buy_order_id = buy_order.order_id
        self.sell_order_id = sell_order.order_id
        self.buyer_id = buy_order.user_id
        self.seller_id = sell_order.user_id
        self.buyer_name = buy_order.username
        self.seller_name = sell_order.username
        self.symbol = buy_order.symbol
        self.price = price
        self.quantity = quantity
        self.total = round(price * quantity, 6)
        self.timestamp = datetime.now()
        self._last_price = None

    def to_dict(self) -> dict:
        return {
            "buyer": self.buyer_name,
            "seller": self.seller_name,
            "price": self.price,
            "quantity": self.quantity,
            "total": self.total,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id
        }


class MatchingEngine:
    """
    Moteur d'appariement.

    Fonctionnement :
    1. Reçoit un ordre (déjà validé par le portfolio).
    2. Si LIMIT : tente de matcher avec les ordres opposés.
       Si pas de contrepartie → ajout au carnet.
    3. Si MARKET : matche avec les meilleurs ordres opposés
       jusqu'à épuisement de la quantité ou du carnet opposé.

    Les callbacks permettent au moteur de notifier l'extérieur
    (portfolio, API, WebSocket) sans dépendre de ces modules.
    """

    def __init__(self, order_book: OrderBook):
        self.order_book = order_book
        self.trades: List[Trade] = []
        self._last_price = None  # ← AJOUTE CETTE LIGNE

        # Callbacks (injectés après création)
        self.on_trade: Optional[Callable] = None
        self.on_order_filled: Optional[Callable] = None
        self.on_funds_check: Optional[Callable] = None

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------

    def process_order(self, order: Order) -> List[Trade]:
        """
        Traite un nouvel ordre.
        Retourne la liste des trades générés.
        """
        if order.order_type == OrderType.LIMIT:
            return self._process_limit_order(order)
        elif order.order_type == OrderType.MARKET:
            return self._process_market_order(order)
        else:
            raise ValueError(f"Type d'ordre inconnu : {order.order_type}")

    # ------------------------------------------------------------------
    # Traitement LIMIT
    # ------------------------------------------------------------------

    def _process_limit_order(self, order: Order) -> List[Trade]:
        """
        Tente de matcher un ordre limité.
        Si pas de contrepartie, l'ajoute au carnet.
        """
        trades = self._match(order)

        # S'il reste quelque chose et que l'ordre est LIMIT → carnet
        if order.remaining_qty > 0 and order.is_active:
            self.order_book.add_order(order)

        return trades

    # ------------------------------------------------------------------
    # Traitement MARKET
    # ------------------------------------------------------------------

    def _process_market_order(self, order: Order) -> List[Trade]:
        """
        Exécute un ordre au marché contre le carnet opposé.
        Prend tout ce qui est disponible jusqu'à épuisement.
        """
        trades = self._match(order, is_market=True)

        # Un ordre MARKET non exécuté entièrement est annulé
        if order.remaining_qty > 0:
            order.status = OrderStatus.CANCELLED

        return trades

    # ------------------------------------------------------------------
    # Algorithme de matching
    # ------------------------------------------------------------------

    def _match(self, order: Order, is_market: bool = False) -> List[Trade]:
        """
        Tente de matcher l'ordre avec le carnet opposé.

        Pour un LIMIT :
            - BUY  : matche tant que le prix ask <= prix de l'ordre
            - SELL : matche tant que le prix bid >= prix de l'ordre

        Pour un MARKET :
            - Matche avec tout le carnet opposé, peu importe le prix.

        Vérifie les fonds des DEUX parties à chaque trade.
        """
        trades = []

        while order.remaining_qty > 0:
            opposite = self._get_best_opposite(order)

            if opposite is None:
                break  # Plus de contrepartie

            # Vérifie si le prix est compatible
            if not is_market:
                if order.side == OrderSide.BUY:
                    if opposite.price > order.price:
                        break  # Le vendeur demande trop cher
                else:  # SELL
                    if opposite.price < order.price:
                        break  # L'acheteur ne propose pas assez

            # Prix d'exécution : celui de l'ordre qui était déjà dans le carnet
            trade_price = opposite.price

            # Quantité échangée = le plus petit des deux restants
            trade_qty = min(order.remaining_qty, opposite.remaining_qty)

            # Vérification des fonds des DEUX parties
            if self.on_funds_check:
                try:
                    self.on_funds_check(order, opposite, trade_price, trade_qty)
                except (InsufficientFundsError, InsufficientAssetsError):
                    # Si l'ordre opposé ne peut pas honorer, on le retire
                    self.order_book.remove_order(opposite.order_id)
                    continue

            # --- Exécution du trade ---
            order.fill(trade_qty)
            opposite.fill(trade_qty)

            trade = Trade(
                buy_order=order if order.side == OrderSide.BUY else opposite,
                sell_order=order if order.side == OrderSide.SELL else opposite,
                price=trade_price,
                quantity=trade_qty
            )
            trades.append(trade)
            self.trades.append(trade)

            # Notification
            if self.on_trade:
                self.on_trade(trade)

            # Si l'ordre opposé est full → retirer du carnet
            if opposite.is_filled:
                self.order_book.remove_order(opposite.order_id)
                if self.on_order_filled:
                    self.on_order_filled(opposite)

        # Si l'ordre entrant est full
        if order.is_filled and self.on_order_filled:
            self.on_order_filled(order)

        return trades

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _get_best_opposite(self, order: Order) -> Optional[Order]:
        """
        Retourne le meilleur ordre opposé dans le carnet.
        Ignore les ordres du même utilisateur (pas de self-trading).
        """
        opposite_list = self.order_book.asks if order.side == OrderSide.BUY else self.order_book.bids

        for o in opposite_list:
            if o.user_id != order.user_id and o.is_active:
                return o
        return None

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    def get_recent_trades(self, limit: int = 20) -> List[dict]:
        """Retourne les derniers trades (pour l'API)."""
        return [t.to_dict() for t in self.trades[-limit:]]

    def get_last_price(self) -> Optional[float]:
        if self.trades:
            return self.trades[-1].price
        return self._last_price

    def reset(self):
        """Réinitialise le moteur (nouveau départ)."""
        self.trades.clear()
        self.order_book.bids.clear()
        self.order_book.asks.clear()
        self.order_book._order_index.clear()
