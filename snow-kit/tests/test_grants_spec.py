"""Grant normalization and spec explanation tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from snow_kit.core.config import SnowKitConfig
from snow_kit.core.grants import has_grant, normalize_grants, required_privilege
from snow_kit.services.catalog.core import catalog_check_write_access
from snow_kit.services.catalog.models import CatalogCheckWriteAccessInput


def test_grants_normalize_and_match() -> None:
    grants = normalize_grants([
        {"privilege": "INSERT", "granted_on": "TABLE", "name": "EXAMPLE_DB.SCRATCH.DEMO"},
    ])

    ok, matches = has_grant(grants, object_name="EXAMPLE_DB.SCRATCH.DEMO", operation="INSERT")

    assert ok is True
    assert matches[0].privilege == "INSERT"
    assert required_privilege("CREATE TABLE") == "CREATE TABLE"


def test_merge_requires_insert_and_update() -> None:
    grants = normalize_grants([
        {"privilege": "INSERT", "granted_on": "TABLE", "name": "EXAMPLE_DB.SCRATCH.DEMO"},
    ])

    ok, _ = has_grant(grants, object_name="EXAMPLE_DB.SCRATCH.DEMO", operation="MERGE")

    assert ok is False

    grants = normalize_grants([
        {"privilege": "INSERT", "granted_on": "TABLE", "name": "EXAMPLE_DB.SCRATCH.DEMO"},
        {"privilege": "UPDATE", "granted_on": "TABLE", "name": "EXAMPLE_DB.SCRATCH.DEMO"},
    ])
    ok, _ = has_grant(grants, object_name="EXAMPLE_DB.SCRATCH.DEMO", operation="MERGE")

    assert ok is True


def test_check_write_access_degrades_without_spec(fake_session) -> None:
    out = catalog_check_write_access(
        CatalogCheckWriteAccessInput(object_name="EXAMPLE_DB.SCRATCH.DEMO", operation="INSERT"),
        session=fake_session,
    )

    assert out.data.has_snowflake_grant is True
    assert out.data.active_role == "U_EXAMPLE"
    assert out.data.spec_available is False
    assert out.warnings


def test_check_write_access_enriches_with_spec(tmp_path: Path, fake_session) -> None:
    spec = tmp_path / "specs" / "prod" / "us" / "teams" / "card.yaml"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        """
roles:
  - T_ANALYTICS:
      privileges:
        tables:
          write:
            - EXAMPLE_DB.SCRATCH.*
  - U_EXAMPLE:
      member_of:
        - T_ANALYTICS
users:
  - fixture.operator@example.invalid:
      can_login: true
      member_of:
        - U_EXAMPLE
""",
        encoding="utf-8",
    )
    fake_session.config = SnowKitConfig(spec_path=tmp_path)

    out = catalog_check_write_access(
        CatalogCheckWriteAccessInput(
            object_name="EXAMPLE_DB.SCRATCH.DEMO",
            operation="INSERT",
            role="U_EXAMPLE",
            email="fixture.operator@example.invalid",
        ),
        session=fake_session,
    )

    assert out.data.spec_available is True
    assert out.data.live_grants_decisive is True
    assert out.data.roles_for_email == ["T_ANALYTICS", "U_EXAMPLE"]
    assert out.data.spec_matches[0]["role"] == "T_ANALYTICS"
    assert out.data.spec_matches[0]["source"] == (
        "specs/prod/us/teams/card.yaml"
    )
    assert out.data.spec_matches[0]["notes"] == ["inherited through U_EXAMPLE"]


def test_permission_spec_wildcards_are_segment_aware(tmp_path: Path, fake_session) -> None:
    spec = tmp_path / "specs" / "prod" / "us" / "teams" / "card.yml"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        """
roles:
  - U_EXAMPLE:
      privileges:
        tables:
          write:
            - EXAMPLE_DB.SCRATCH.*
users: []
""",
        encoding="utf-8",
    )
    fake_session.config = SnowKitConfig(spec_path=tmp_path)

    out = catalog_check_write_access(
        CatalogCheckWriteAccessInput(
            object_name="EXAMPLE_DB.SCRATCHY.DEMO",
            operation="INSERT",
            role="U_EXAMPLE",
        ),
        session=fake_session,
    )

    assert out.data.spec_matches == []


def test_unknown_permission_schema_only_warns(tmp_path: Path, fake_session) -> None:
    spec = tmp_path / "specs" / "prod" / "us" / "teams" / "unknown.yml"
    spec.parent.mkdir(parents=True)
    spec.write_text("role: U_EXAMPLE\nprivileges: '*'\n", encoding="utf-8")
    fake_session.config = SnowKitConfig(spec_path=tmp_path)

    out = catalog_check_write_access(
        CatalogCheckWriteAccessInput(
            object_name="EXAMPLE_DB.SCRATCH.DEMO",
            operation="INSERT",
            role="U_EXAMPLE",
        ),
        session=fake_session,
    )

    assert out.data.has_snowflake_grant is True
    assert out.data.spec_matches == []
    assert any("unknown permission schema" in warning for warning in out.warnings)


@pytest.mark.skipif(sys.platform == "darwin", reason="Path.rglob does not follow directory symlinks on macOS")
def test_permission_spec_skips_directory_symlink_escape(
    tmp_path: Path,
    fake_session,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_spec = outside / "escape.yml"
    outside_spec.write_text(
        """
roles:
  - U_EXAMPLE:
      privileges:
        tables:
          write:
            - EXAMPLE_DB.SCRATCH.*
users: []
""",
        encoding="utf-8",
    )
    root = tmp_path / "spec-root"
    root.mkdir()
    (root / "specs" / "prod" / "us" / "teams").mkdir(parents=True)
    (root / "specs" / "prod" / "us" / "teams" / "escape").symlink_to(outside, target_is_directory=True)
    fake_session.config = SnowKitConfig(spec_path=root)

    out = catalog_check_write_access(
        CatalogCheckWriteAccessInput(
            object_name="EXAMPLE_DB.SCRATCH.DEMO",
            operation="INSERT",
            role="U_EXAMPLE",
        ),
        session=fake_session,
    )

    assert out.data.spec_matches == []
    assert any("outside configured root" in warning for warning in out.warnings)
