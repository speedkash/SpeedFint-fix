"""
Exceptions personnalisées pour le marché FIX.
Chaque erreur métier a sa propre classe pour un debugging clair.
"""


class MarketError(Exception):
    """Classe de base pour toutes les erreurs du marché."""
    pass


# --- Erreurs liées aux ordres ---

class InvalidOrderError(MarketError):
    """L'ordre est mal formé (prix négatif, quantité invalide, etc.)."""
    pass


class OrderNotFoundError(MarketError):
    """L'ordre demandé n'existe pas (annulation d'un ordre inexistant)."""
    pass


# --- Erreurs liées au portefeuille ---

class InsufficientFundsError(MarketError):
    """L'utilisateur n'a pas assez de cash pour passer l'ordre."""
    pass


class InsufficientAssetsError(MarketError):
    """L'utilisateur n'a pas assez de FIX pour passer l'ordre de vente."""
    pass


# --- Erreurs liées au compte ---

class UserNotFoundError(MarketError):
    """L'utilisateur n'existe pas."""
    pass


class AuthenticationError(MarketError):
    """Login ou mot de passe invalide."""
    pass


class UsernameAlreadyExistsError(MarketError):
    """Le nom d'utilisateur est déjà pris."""
    pass


# --- Erreurs liées au marché ---

class MarketClosedError(MarketError):
    """Le marché est fermé (pour plus tard si horaires)."""
    pass


class InvalidSymbolError(MarketError):
    """Le symbole demandé n'est pas listé sur le marché."""
    pass
