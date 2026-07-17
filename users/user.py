"""
Classe User : représente un participant au marché FIX.
"""

import hashlib
import uuid
from typing import Optional
from users.portfolio import Portfolio


class User:
    """
    Utilisateur du marché FIX.

    Attributs :
        user_id   : Identifiant unique
        username  : Nom d'utilisateur (unique)
        password_hash : Hash SHA-256 du mot de passe
        role      : "admin" ou "user"
        portfolio : Son portefeuille (cash + FIX)
        is_bot    : True si c'est un bot
    """

    def __init__(self, username: str, password: str,
                 role: str = "user", is_bot: bool = False,
                 user_id: Optional[int] = None):
        self.user_id = user_id or self._generate_id()
        self.username = username
        self.password_hash = self._hash_password(password)
        self.role = role
        self.is_bot = is_bot
        self.portfolio = Portfolio(self.user_id, self.username)

    # ------------------------------------------------------------------
    # Authentification
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash le mot de passe en SHA-256 (simple, pour prototype)."""
        return hashlib.sha256(password.encode()).hexdigest()

    def check_password(self, password: str) -> bool:
        """Vérifie si le mot de passe correspond."""
        return self.password_hash == self._hash_password(password)

    # ------------------------------------------------------------------
    # ID
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_id() -> int:
        """Génère un ID unique (basé sur UUID4 tronqué)."""
        return int(uuid.uuid4().int & 0x7FFFFFFF)

    # ------------------------------------------------------------------
    # Méthodes de trading (délèguent au portfolio)
    # ------------------------------------------------------------------

    def can_buy(self, price: float, quantity: int,
                fee: float = 0.0) -> bool:
        return self.portfolio.can_buy(price, quantity, fee)

    def can_sell(self, symbol: str, quantity: int) -> bool:
        return self.portfolio.can_sell(symbol, quantity)

    # ------------------------------------------------------------------
    # Sérialisation
    # ------------------------------------------------------------------

    def to_dict(self, include_sensitive: bool = False) -> dict:
        """
        Sérialise l'utilisateur.
        include_sensitive=False → pas de hash de mot de passe.
        """
        data = {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "is_bot": self.is_bot,
            "portfolio": self.portfolio.to_dict()
        }
        if include_sensitive:
            data["password_hash"] = self.password_hash
        return data

    def __repr__(self) -> str:
        return f"User({self.username}, {self.role})"
