"""
Gestion du portefeuille d'un utilisateur : cash + positions en FIX.
Vérifie la solvabilité avant chaque ordre.
"""

from typing import Dict, Optional
from core.exceptions import InsufficientFundsError, InsufficientAssetsError


class Portfolio:
    """
    Portefeuille d'un utilisateur.

    Attributs :
        user_id    : ID de l'utilisateur
        username   : Nom de l'utilisateur
        cash       : Solde en USD (jamais négatif)
        assets     : Dict { symbole -> quantité } (positions détenues)
        blocked_cash   : Cash réservé par des ordres en attente
        blocked_assets : Actifs réservés par des ordres en attente
    """

    def __init__(self, user_id: int, username: str,
                 initial_cash: float = 0.0,
                 initial_assets: Optional[Dict[str, int]] = None):
        self.user_id = user_id
        self.username = username
        self.cash = initial_cash
        self.assets = initial_assets or {}
        self.blocked_cash = 0.0
        self.blocked_assets: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Propriétés calculées
    # ------------------------------------------------------------------

    @property
    def available_cash(self) -> float:
        """Cash disponible pour de nouveaux ordres."""
        return round(self.cash - self.blocked_cash, 6)

    def available_asset(self, symbol: str) -> int:
        """Quantité disponible de l'actif (FIX)."""
        owned = self.assets.get(symbol, 0)
        blocked = self.blocked_assets.get(symbol, 0)
        return owned - blocked

    # ------------------------------------------------------------------
    # Vérifications de solvabilité
    # ------------------------------------------------------------------

    def can_buy(self, price: float, quantity: int,
                include_fee: float = 0.0) -> bool:
        """
        Vérifie si l'utilisateur peut acheter.
        Coût total = prix * quantité + frais éventuels.
        """
        total_cost = price * quantity + include_fee
        return self.available_cash >= total_cost

    def can_sell(self, symbol: str, quantity: int) -> bool:
        """Vérifie si l'utilisateur possède assez d'actifs pour vendre."""
        return self.available_asset(symbol) >= quantity

    # ------------------------------------------------------------------
    # Blocage / Déblocage des fonds
    # ------------------------------------------------------------------

    def block_funds_for_buy(self, price: float, quantity: int,
                            fee: float = 0.0):
        """
        Bloque le cash nécessaire pour un ordre d'achat.
        Lève InsufficientFundsError si pas assez.
        """
        total = price * quantity + fee
        if self.available_cash < total:
            raise InsufficientFundsError(
                f"{self.username} : besoin de {total:.4f} $, "
                f"disponible : {self.available_cash:.4f} $"
            )
        self.blocked_cash += total

    def block_assets_for_sell(self, symbol: str, quantity: int):
        """
        Bloque les actifs nécessaires pour un ordre de vente.
        Lève InsufficientAssetsError si pas assez.
        """
        if self.available_asset(symbol) < quantity:
            raise InsufficientAssetsError(
                f"{self.username} : besoin de {quantity} {symbol}, "
                f"disponible : {self.available_asset(symbol)}"
            )
        self.blocked_assets[symbol] = self.blocked_assets.get(symbol, 0) + quantity

    def release_funds_for_buy(self, price: float, quantity: int,
                              fee: float = 0.0):
        """Débloque le cash d'un ordre d'achat (annulation ou exécution partielle)."""
        total = price * quantity + fee
        self.blocked_cash = max(0, self.blocked_cash - total)

    def release_assets_for_sell(self, symbol: str, quantity: int):
        """Débloque les actifs d'un ordre de vente (sans toucher au total)."""
        self.blocked_assets[symbol] = max(
            0, self.blocked_assets.get(symbol, 0) - quantity
        )

    # ------------------------------------------------------------------
    # Règlement d'un trade
    # ------------------------------------------------------------------

    def apply_buy(self, price: float, quantity: int,
                  fee: float = 0.0, release_blocked: int = 0):
        """
        Exécute un achat :
        - Débite le cash du prix * quantité + frais
        - Crédite les actifs
        - Débloque la partie exécutée
        - Vérifie STRICTEMENT que le cash est suffisant
        """
        total = price * quantity
        total_with_fee = total + fee

        # VÉRIFICATION STRICTE : le cash ne doit jamais devenir négatif
        if self.cash < total_with_fee:
            raise InsufficientFundsError(
                f"{self.username} : cash insuffisant pour l'achat "
                f"({total_with_fee:.4f} $ nécessaires, {self.cash:.4f} $ disponibles)"
            )

        self.cash -= total_with_fee
        self.assets["FIX"] = self.assets.get("FIX", 0) + quantity

        # Débloque la partie qui était réservée
        if release_blocked > 0:
            blocked_total = price * release_blocked
            self.blocked_cash = max(0, self.blocked_cash - blocked_total)

    def apply_sell(self, price: float, quantity: int,
                   fee: float = 0.0, release_blocked: int = 0):
        """
        Exécute une vente :
        - Débite les actifs
        - Crédite le cash du prix * quantité - frais
        - Débloque la partie exécutée
        - Vérifie STRICTEMENT que les actifs sont suffisants
        """
        current = self.assets.get("FIX", 0)
        if current < quantity:
            raise InsufficientAssetsError(
                f"{self.username} : FIX insuffisants pour la vente "
                f"({quantity} nécessaires, {current} disponibles)"
            )

        self.assets["FIX"] = current - quantity
        self.cash += price * quantity
        self.cash -= fee

        # Débloque la partie qui était réservée
        if release_blocked > 0:
            self.blocked_assets["FIX"] = max(
                0, self.blocked_assets.get("FIX", 0) - release_blocked
            )

    # ------------------------------------------------------------------
    # Administration
    # ------------------------------------------------------------------

    def add_cash(self, amount: float):
        """Ajoute du cash (admin seulement)."""
        if amount < 0:
            raise ValueError("Le montant doit être positif")
        self.cash += amount

    def add_assets(self, symbol: str, quantity: int):
        """Ajoute des actifs (admin seulement)."""
        if quantity < 0:
            raise ValueError("La quantité doit être positive")
        self.assets[symbol] = self.assets.get(symbol, 0) + quantity

    # ------------------------------------------------------------------
    # Sérialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "cash": round(self.cash, 6),
            "available_cash": round(self.available_cash, 6),
            "blocked_cash": round(self.blocked_cash, 6),
            "assets": self.assets,
            "available_assets": {
                sym: self.available_asset(sym) for sym in self.assets
            },
            "blocked_assets": self.blocked_assets
        }

    def __repr__(self) -> str:
        return (
            f"Portfolio({self.username}: "
            f"{self.cash:.2f} $, "
            f"FIX: {self.assets.get('FIX', 0)})"
        )
