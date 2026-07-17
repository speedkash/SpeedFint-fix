"""
Carnet d'ordres pour un actif (FIX).
Maintient les listes d'ordres acheteurs et vendeurs.
"""

from typing import List, Optional, Tuple
from .order import Order, OrderSide, OrderType, OrderStatus


class OrderBook:
    """
    Carnet d'ordres pour un seul actif.

    Deux listes :
        bids : ordres d'achat, triés par prix décroissant,
               puis quantité décroissante, puis timestamp croissant.
        asks : ordres de vente, triés par prix croissant,
               puis quantité décroissante, puis timestamp croissant.

    Priorité d'exécution : Prix > Quantité > Temps
    """

    def __init__(self, symbol: str = "FIX"):
        self.symbol = symbol
        self.bids: List[Order] = []  # Acheteurs
        self.asks: List[Order] = []  # Vendeurs
        self._order_index: dict = {}  # Accès rapide par order_id

    # ------------------------------------------------------------------
    # Propriétés publiques (utilisées par l'API)
    # ------------------------------------------------------------------

    @property
    def best_bid(self) -> Optional[float]:
        """Meilleur prix d'achat (le plus élevé)."""
        if self.bids:
            return self.bids[0].price
        return None

    @property
    def best_ask(self) -> Optional[float]:
        """Meilleur prix de vente (le plus bas)."""
        if self.asks:
            return self.asks[0].price
        return None

    @property
    def spread(self) -> Optional[float]:
        """Écart entre le meilleur ask et le meilleur bid."""
        if self.best_bid is not None and self.best_ask is not None:
            return round(self.best_ask - self.best_bid, 6)
        return None

    def get_order(self, order_id: str) -> Optional[Order]:
        """Récupère un ordre par son ID."""
        return self._order_index.get(order_id)

    # ------------------------------------------------------------------
    # Ajout d'un ordre
    # ------------------------------------------------------------------

    def add_order(self, order: Order):
        """
        Ajoute un ordre dans le carnet.
        L'ordre est inséré à sa place selon les règles de priorité.
        """
        if order.side == OrderSide.BUY:
            self._insert_sorted(self.bids, order, reverse=True)
        else:
            self._insert_sorted(self.asks, order, reverse=False)

        self._order_index[order.order_id] = order

    def _insert_sorted(self, orders: List[Order], order: Order,
                       reverse: bool):
        """
        Insère l'ordre dans la liste au bon endroit.
        Tri : prix (meilleur d'abord), puis quantité (plus grosse d'abord),
              puis timestamp (plus ancien d'abord).
        """
        # Pour les bids : prix décroissant (reverse=True)
        # Pour les asks : prix croissant (reverse=False)
        for i, existing in enumerate(orders):
            if self._has_priority(order, existing, reverse):
                orders.insert(i, order)
                return
        orders.append(order)

    def _has_priority(self, new: Order, existing: Order,
                      reverse: bool) -> bool:
        """
        Détermine si `new` doit être placé avant `existing`.
        Priorité : 1. Prix  2. Quantité  3. Temps
        """
        if reverse:
            # Bids : prix le plus élevé en premier
            if new.price > existing.price:
                return True
            if new.price < existing.price:
                return False
        else:
            # Asks : prix le plus bas en premier
            if new.price < existing.price:
                return True
            if new.price > existing.price:
                return False

        # Prix égal : plus grosse quantité en premier
        if new.quantity > existing.quantity:
            return True
        if new.quantity < existing.quantity:
            return False

        # Quantité égale : plus ancien en premier
        return new.timestamp < existing.timestamp

    # ------------------------------------------------------------------
    # Suppression d'un ordre
    # ------------------------------------------------------------------

    def remove_order(self, order_id: str) -> Order:
        """
        Retire un ordre du carnet (annulation ou exécution complète).
        Retourne l'ordre retiré.
        """
        order = self._order_index.pop(order_id, None)
        if order is None:
            return None

        if order.side == OrderSide.BUY:
            self.bids.remove(order)
        else:
            self.asks.remove(order)

        return order

    def cancel_order(self, order_id: str) -> Order:
        """
        Annule un ordre. Lève une erreur si l'ordre n'est pas trouvé
        ou s'il n'est plus actif.
        """
        order = self.get_order(order_id)
        if order is None:
            from core.exceptions import OrderNotFoundError
            raise OrderNotFoundError(f"Ordre {order_id} introuvable")

        order.cancel()  # Lève une erreur si déjà exécuté/annulé
        self.remove_order(order_id)
        return order

    # ------------------------------------------------------------------
    # Nettoyage
    # ------------------------------------------------------------------

    def clean_filled_orders(self):
        """Retire du carnet tous les ordres entièrement exécutés."""
        self.bids = [o for o in self.bids if o.is_active]
        self.asks = [o for o in self.asks if o.is_active]
        # Nettoie aussi l'index
        self._order_index = {
            oid: o for oid, o in self._order_index.items() if o.is_active
        }

    # ------------------------------------------------------------------
    # Sérialisation
    # ------------------------------------------------------------------

    def get_book_snapshot(self, depth: int = 10) -> dict:
        """
        Retourne une vue résumée du carnet pour l'API.
        depth = nombre de niveaux à afficher.
        """
        bids_summary = []
        for o in self.bids[:depth]:
            if o.is_active:
                bids_summary.append({
                    "price": o.price,
                    "quantity": o.remaining_qty,
                    "orders": 1  # Simplifié : on pourrait compter les ordres
                })

        asks_summary = []
        for o in self.asks[:depth]:
            if o.is_active:
                asks_summary.append({
                    "price": o.price,
                    "quantity": o.remaining_qty,
                    "orders": 1
                })

        return {
            "symbol": self.symbol,
            "bids": bids_summary,
            "asks": asks_summary,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "spread": self.spread
        }

    def __repr__(self) -> str:
        return (
            f"OrderBook({self.symbol}: "
            f"{len(self.bids)} bids, {len(self.asks)} asks)"
        )
