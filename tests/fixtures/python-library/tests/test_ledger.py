"""Fixture test source; the documentation pipeline must not run it."""
import pytest
from ledger import Account


def test_failure_preserves_balance():
    account = Account(10)
    with pytest.raises(ValueError, match="insufficient balance"):
        account.debit(11)
    assert account.balance == 10
