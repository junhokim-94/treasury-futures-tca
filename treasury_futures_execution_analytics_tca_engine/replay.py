from __future__ import annotations

from collections.abc import Iterable

from .order_book import OrderBook
from .types import MBOEvent


def replay_events(
    events: Iterable[MBOEvent],
    book: OrderBook,
    snapshot_every: int = 0,
    validate_every: int = 0,
) -> list[dict[str, object]]:
    snapshots: list[dict[str, object]] = []
    snapshot_due = False
    validation_due = False
    for index, event in enumerate(events, start=1):
        book.apply_event(event)
        if validate_every > 0 and index % validate_every == 0:
            validation_due = True
        if snapshot_every > 0 and index % snapshot_every == 0:
            snapshot_due = True
        if not event.is_event_end:
            continue
        if validation_due:
            book.validate()
            validation_due = False
        if snapshot_due:
            snapshots.append(book.snapshot_top_n())
            snapshot_due = False
    return snapshots

