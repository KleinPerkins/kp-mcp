"""Batching utilities for google-kit core (R23).

- paginate:        Generic pagination iterator over page-fetch callables.
- chunk_requests:  Split a list of requests into batchUpdate-sized chunks.
- build_field_mask: Compose a Google API partial-response field mask.
- byte_chunks:     Yield (start, end, chunk) for resumable/chunked transfer.

Phase 4 wires API-specific request builders on top of these primitives.
"""
from __future__ import annotations

from typing import Any, Callable, Iterator


def paginate(
    fetch_page: Callable[[str | None], tuple[list[Any], str | None]],
) -> Iterator[Any]:
    """Yield items from paginated responses.

    Args:
        fetch_page: Callable(page_token | None) → (items, next_token | None).
                    Returns (items, None) to signal the last page.

    Yields:
        Individual items across all pages in order.
    """
    token: str | None = None
    while True:
        items, token = fetch_page(token)
        yield from items
        if token is None:
            break


def chunk_requests(
    requests: list[Any],
    chunk_size: int,
) -> Iterator[list[Any]]:
    """Yield sub-lists of at most chunk_size items for batchUpdate aggregation.

    Args:
        requests:   Full list of requests to batch.
        chunk_size: Maximum requests per chunk (must be >= 1).

    Yields:
        Sub-lists of at most chunk_size items.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size!r}")
    for i in range(0, len(requests), chunk_size):
        yield requests[i : i + chunk_size]


def build_field_mask(*fields: str) -> str:
    """Build a comma-separated field mask string for partial-response requests.

    Pass individual field paths; returns a Google-API-compatible field mask.
    Returns '*' (all fields) when called with no arguments.

    Phase 4 adds service-specific field-mask presets on top of this helper.
    """
    if not fields:
        return "*"
    return ",".join(sorted(fields))


def byte_chunks(
    data: bytes,
    chunk_size: int,
) -> Iterator[tuple[int, int, bytes]]:
    """Yield (start, end_exclusive, chunk) tuples for resumable/chunked uploads.

    Args:
        data:       Raw bytes to split.
        chunk_size: Maximum bytes per chunk (must be >= 1).

    Yields:
        (start_byte, end_byte_exclusive, chunk) for each chunk.

    Phase 4 wires this into Drive resumable upload sessions.
    """
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size!r}")
    total = len(data)
    offset = 0
    while offset < total:
        end = min(offset + chunk_size, total)
        yield offset, end, data[offset:end]
        offset = end
