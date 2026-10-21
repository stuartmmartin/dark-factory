"""SQLAdmin acceptors: humans verify the ledger's pure policies by hand (A5)."""

from __future__ import annotations

from ledger.application.policies import allocation, double_entry
from sb_admin.acceptor import Acceptor

ACCEPTORS = [
    Acceptor(
        "allocation",
        "Allocation",
        allocation.AllocationInput,
        allocation.allocation_acceptor,
        version=allocation.VERSION,
        description=(
            "Split a total by weights (largest remainder). The parts always sum to the total; "
            "a zero weight gets zero."
        ),
    ),
    Acceptor(
        "journal-entry",
        "Journal entry",
        double_entry.JournalEntryInput,
        double_entry.journal_entry_acceptor,
        version=double_entry.VERSION,
        description=(
            "Check that an entry balances: total debits must equal total credits. Amounts must "
            "be positive and within the currency's minor units (never rounded)."
        ),
    ),
    Acceptor(
        "transfer",
        "Transfer",
        double_entry.TransferInput,
        double_entry.transfer_acceptor,
        version=double_entry.VERSION,
        description=(
            "The entry `ledger-cli transfer` posts: it debits the To account and credits the From "
            "account by the same amount, then checks it balances. Account names are labels only; "
            "nothing is read or written."
        ),
    ),
]
