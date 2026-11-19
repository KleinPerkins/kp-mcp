"""Focused tests for the bounded snow-kit MCP resource catalog."""
from __future__ import annotations

import asyncio
import json
from importlib.resources import files
from typing import Any

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import (
    INVALID_PARAMS,
    ListResourcesRequest,
    ReadResourceRequest,
    ReadResourceRequestParams,
)

from snow_kit.mcp import build_mcp_server
from snow_kit.mcp.resources import (
    SOURCE_STATUS_URI,
    guidance_documents,
    list_catalog_resources,
    read_catalog_resource,
)

_EXPECTED_URIS = [
    "snow-kit://guidance/query-safety",
    "snow-kit://guidance/analytics-workflow",
    "snow-kit://guidance/permissions-and-recovery",
    SOURCE_STATUS_URI,
]


@pytest.fixture(autouse=True)
def _isolated_context_profile(tmp_path, monkeypatch):
    """Dynamic resource tests must not read the operator's context configuration."""
    from snow_kit.core.config import CONFIG_PATH_ENV, profile_keys

    for key in profile_keys():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(CONFIG_PATH_ENV, str(tmp_path / "absent-profile.env"))


def _root(result: Any) -> Any:
    return getattr(result, "root", result)


def test_resource_catalog_is_exact_bounded_and_deterministic() -> None:
    first = list_catalog_resources()
    second = list_catalog_resources()

    assert [str(resource.uri) for resource in first] == _EXPECTED_URIS
    assert [resource.model_dump() for resource in first] == [
        resource.model_dump() for resource in second
    ]
    assert all(
        resource.size is not None and resource.size <= 16 * 1024
        for resource in first[:-1]
    )
    assert first[-1].size is None
    assert [resource.mimeType for resource in first] == [
        "text/markdown",
        "text/markdown",
        "text/markdown",
        "application/json",
    ]
    assert all(resource.annotations is not None for resource in first)
    assert all(resource.annotations.priority is not None for resource in first)
    assert all(resource.annotations.audience for resource in first)


def test_resource_listing_does_not_read_dynamic_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "snow_kit.mcp.resources.context_source_status",
        lambda: (_ for _ in ()).throw(AssertionError("dynamic source was read")),
    )

    resources = list_catalog_resources()

    assert str(resources[-1].uri) == SOURCE_STATUS_URI


def test_static_guidance_is_rendered_from_one_packaged_catalog() -> None:
    catalog = files("snow_kit.data.guidance").joinpath("catalog.json")
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    documents = guidance_documents()

    assert payload["schema_version"] == 1
    assert len(payload["resources"]) == len(documents) == 3
    assert "max_rows only caps rows returned" in documents[0].content
    assert "Separate authoritative business meaning" in documents[1].content
    assert "Snowflake remains authoritative" in documents[2].content


def test_server_lists_and_reads_every_resource() -> None:
    server = build_mcp_server()
    list_handler = server.request_handlers[ListResourcesRequest]
    read_handler = server.request_handlers[ReadResourceRequest]

    listed = _root(
        asyncio.run(list_handler(ListResourcesRequest(method="resources/list")))
    )
    assert [str(resource.uri) for resource in listed.resources] == _EXPECTED_URIS

    for resource in listed.resources:
        result = _root(
            asyncio.run(
                read_handler(
                    ReadResourceRequest(
                        method="resources/read",
                        params=ReadResourceRequestParams(uri=resource.uri),
                    )
                )
            )
        )
        assert len(result.contents) == 1
        assert result.contents[0].text
        assert result.contents[0].mimeType == resource.mimeType


def test_source_status_is_redacted_bounded_json() -> None:
    contents = list(read_catalog_resource(SOURCE_STATUS_URI))
    text = str(contents[0].content)
    payload = json.loads(text)

    assert len(text.encode("utf-8")) <= 8 * 1024
    assert payload["state"] == "context_unavailable"
    assert payload["source_count"] == 0
    assert payload["sources"] == []
    assert not any(
        forbidden in text.lower()
        for forbidden in ("/users/", "remote", "email", "username")
    )


@pytest.mark.parametrize(
    "uri",
    [
        "snow-kit://guidance/query-safety/",
        "snow-kit://guidance/query-safety?offset=1",
        "snow-kit://context/sources/status/extra",
        "file:///etc/passwd",
    ],
)
def test_resource_reads_require_an_exact_known_uri(uri: str) -> None:
    with pytest.raises(McpError) as exc_info:
        list(read_catalog_resource(uri))

    assert exc_info.value.error.code == INVALID_PARAMS
    assert "resources/list" in exc_info.value.error.message
