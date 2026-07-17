"""
Classe Order : définit un ordre passé sur le marché FIX.
"""

from enum import Enum
from datetime import datetime
import uuid


class OrderSide(Enum):
    """Sens de l'ordre."""
    BUY = "buy"    # Achat
    SELL = "sell"  # Vente


class OrderType(Enum):
    """Type d'ordre."""
    LIMIT = "limit"    # Ordre à cours limité (je fixe mon prix max/min)
    MARKET = "market"  # Ordre au marché (je prends le meilleur prix disponible)


class OrderStatus(Enum):
    """État actuel de l'ordre."""
    OPEN = "open"           # En attente dans le carnet
    PARTIALLY_FILLED = "partially_filled"  # Partiellement exécuté
    FILLED = "filled"       # Entièrement exécuté
    CANCELLED = "cancelled" # Annulé par l'utilisateur


class Order:
    """
    Représente un ordre de bourse.

    Attributs :
        order_id    : Identifiant unique (UUID)
        user_id     : ID de l'utilisateur qui passe l'ordre
        username    : Nom de l'utilisateur (pratique pour l'affichage)
        symbol      : Symbole de l'actif (toujours "FIX" ici)
        side        : BUY ou SELL
        order_type  : LIMIT ou MARKET
        price       : Prix unitaire (None si MARKET)
        quantity    : Quantité totale demandée
        filled_qty  : Quantité déjà exécutée
        status      : État actuel
        timestamp   : Horodatage de création (microsecondes)
    """

    def __init__(self, user_id: int, username: str, side: OrderSide,
                 order_type: OrderType, quantity: int, price: float = None,
                 symbol: str = "FIX"):
        # Validations de base
        if quantity <= 0:
            raise ValueError("La quantité doit être positive")
        if order_type == OrderType.LIMIT and price is not None and price <= 0:
            raise ValueError("Le prix doit être positif pour un ordre limité")

        self.order_id = str(uuid.uuid4())
        self.user_id = user_id
        self.username = username
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.price = price  # None pour les ordres MARKET
        self.quantity = quantity
        self.filled_qty = 0
        self.status = OrderStatus.OPEN
        self.timestamp = datetime.now()

    @property
    def remaining_qty(self) -> int:
        """Quantité restant à exécuter."""
        return self.quantity - self.filled_qty

    @property
    def is_filled(self) -> bool:
        """Vrai si l'ordre est entièrement exécuté."""
        return self.filled_qty >= self.quantity

    @property
    def is_active(self) -> bool:
        """Vrai si l'ordre est encore actif (susceptible d'être exécuté)."""
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    def fill(self, qty: int):
        """
        Exécute une partie (ou la totalité) de l'ordre.
        Met à jour filled_qty et le statut.
        """
        if qty > self.remaining_qty:
            raise ValueError(
                f"Impossible d'exécuter {qty} unités : "
                f"il n'en reste que {self.remaining_qty}"
            )

        self.filled_qty += qty

        if self.is_filled:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

    def cancel(self):
        """Annule l'ordre. Lève une erreur s'il est déjà exécuté ou annulé."""
        if not self.is_active:
            raise ValueError(
                f"Impossible d'annuler un ordre avec le statut {self.status.value}"
            )
        self.status = OrderStatus.CANCELLED

    def to_dict(self) -> dict:
        """Sérialise l'ordre en dictionnaire (pour l'API)."""
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "username": self.username,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "price": self.price,
            "quantity": self.quantity,
            "filled_qty": self.filled_qty,
            "remaining_qty": self.remaining_qty,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat()
        }

    def __repr__(self) -> str:
        return (
            f"Order(id={self.order_id[:8]}..., user={self.username}, "
            f"{self.side.value} {self.quantity} {self.symbol} "
            f"@ {self.price if self.price else 'MARKET'} "
            f"[{self.status.value}]"
        )
