"""
Validation des données entrantes (ordres, création de compte, etc.).
"""

from typing import Optional, Tuple
from core.order import OrderSide, OrderType


def validate_order_params(side: str, order_type: str,
                          quantity: int, price: Optional[float],
                          min_qty: int, max_qty: int) -> Tuple[bool, str]:
    """
    Valide les paramètres d'un ordre.
    Retourne (ok, message_erreur).
    """
    # Sens
    if side not in ("buy", "sell"):
        return False, "Le sens doit être 'buy' ou 'sell'"

    # Type
    if order_type not in ("limit", "market"):
        return False, "Le type doit être 'limit' ou 'market'"

    # Quantité
    if not isinstance(quantity, int) or quantity <= 0:
        return False, "La quantité doit être un entier positif"

    if quantity < min_qty:
        return False, f"Quantité minimum : {min_qty} FIX"
    if quantity > max_qty:
        return False, f"Quantité maximum : {max_qty} FIX"

    # Prix (seulement pour LIMIT)
    if order_type == "limit":
        if price is None:
            return False, "Un prix est requis pour un ordre limité"
        if not isinstance(price, (int, float)) or price <= 0:
            return False, "Le prix doit être un nombre positif"

    return True, ""


def validate_registration(username: str, password: str) -> Tuple[bool, str]:
    """
    Valide les paramètres d'inscription.
    """
    if not username or len(username) < 3:
        return False, "Le nom d'utilisateur doit faire au moins 3 caractères"
    if not username.isalnum():
        return False, "Le nom d'utilisateur ne doit contenir que des lettres et chiffres"
    if not password or len(password) < 4:
        return False, "Le mot de passe doit faire au moins 4 caractères"
    return True, ""


def validate_add_cash(amount: float) -> Tuple[bool, str]:
    """Valide un ajout de cash par l'admin."""
    if not isinstance(amount, (int, float)) or amount <= 0:
        return False, "Le montant doit être un nombre positif"
    if amount > 1_000_000:
        return False, "Montant maximum : 1 000 000 $ par opération"
    return True, ""
