"""Tests for google_kit.core.batch."""
import pytest

from google_kit.core.batch import build_field_mask, byte_chunks, chunk_requests, paginate


def test_paginate_single_page() -> None:
    def fetch(token):
        assert token is None
        return (["a", "b", "c"], None)

    items = list(paginate(fetch))
    assert items == ["a", "b", "c"]


def test_paginate_multiple_pages() -> None:
    pages = [
        (["a", "b"], "tok1"),
        (["c", "d"], "tok2"),
        (["e"], None),
    ]
    calls = []

    def fetch(token):
        calls.append(token)
        return pages[len(calls) - 1]

    items = list(paginate(fetch))
    assert items == ["a", "b", "c", "d", "e"]
    assert calls == [None, "tok1", "tok2"]


def test_paginate_empty_page() -> None:
    def fetch(token):
        return ([], None)

    assert list(paginate(fetch)) == []


def test_chunk_requests_even() -> None:
    chunks = list(chunk_requests(list(range(6)), 2))
    assert chunks == [[0, 1], [2, 3], [4, 5]]


def test_chunk_requests_uneven() -> None:
    chunks = list(chunk_requests(list(range(5)), 2))
    assert chunks == [[0, 1], [2, 3], [4]]


def test_chunk_requests_empty() -> None:
    assert list(chunk_requests([], 3)) == []


def test_chunk_requests_invalid_size() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        list(chunk_requests([1, 2], 0))


def test_build_field_mask_no_args() -> None:
    assert build_field_mask() == "*"


def test_build_field_mask_sorted() -> None:
    result = build_field_mask("c", "a", "b")
    assert result == "a,b,c"


def test_build_field_mask_single() -> None:
    assert build_field_mask("id") == "id"


def test_byte_chunks_exact_division() -> None:
    data = b"abcdef"
    chunks = list(byte_chunks(data, 2))
    assert chunks == [(0, 2, b"ab"), (2, 4, b"cd"), (4, 6, b"ef")]


def test_byte_chunks_remainder() -> None:
    data = b"abcde"
    chunks = list(byte_chunks(data, 2))
    assert chunks == [(0, 2, b"ab"), (2, 4, b"cd"), (4, 5, b"e")]


def test_byte_chunks_larger_than_data() -> None:
    data = b"hi"
    chunks = list(byte_chunks(data, 100))
    assert chunks == [(0, 2, b"hi")]


def test_byte_chunks_empty() -> None:
    assert list(byte_chunks(b"", 4)) == []


def test_byte_chunks_invalid_size() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        list(byte_chunks(b"data", 0))


def test_byte_chunks_reassemble() -> None:
    data = b"hello world this is a test"
    reassembled = b"".join(chunk for _, _, chunk in byte_chunks(data, 7))
    assert reassembled == data
