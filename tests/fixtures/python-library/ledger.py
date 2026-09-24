"""Synthetic test fixture: bounded account transfer, no external dependencies."""
from dataclasses import dataclass


@dataclass
class Account:
    balance: int

    def debit(self, amount: int) -> int:
        if amount <= 0:
            raise ValueError("amount must be positive")
        if amount > self.balance:
            raise ValueError("insufficient balance")
        self.balance -= amount
        return self.balance
