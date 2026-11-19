"""Build the wheel and prove packaged resources load without the source tree."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


def test_isolated_wheel_contains_and_reads_every_packaged_resource(
    tmp_path: Path,
) -> None:
    workspace = Path(__file__).parents[2]
    dist = tmp_path / "dist"
    subprocess.run(
        [
            "uv",
            "build",
            "--package",
            "snow-kit",
            "--out-dir",
            str(dist),
        ],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = sorted(dist.glob("snow_kit-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]

    with zipfile.ZipFile(wheel) as archive:
        packaged = set(archive.namelist())
        packaged_intents = archive.read("snow_kit/docs/INTENTS.md")
        metadata_name = next(
            name for name in packaged if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")
    assert {
        "snow_kit/data/config.env.template",
        "snow_kit/data/guidance/catalog.json",
        "snow_kit/docs/INTENTS.md",
    } <= packaged
    assert packaged_intents == (
        workspace / "snow-kit" / "docs" / "INTENTS.md"
    ).read_bytes()
    assert "Requires-Dist: kp-mcp-bootstrap==0.4.0" in metadata

    script = """
import json
import sys
from importlib.resources import files
sys.path.insert(0, sys.argv[1])
import snow_kit
from snow_kit.mcp.resources import guidance_documents, list_catalog_resources, read_catalog_resource
resources = list_catalog_resources()
intent_manifest = files("snow_kit").joinpath("docs", "INTENTS.md").read_text(encoding="utf-8")
payload = {
    "module": snow_kit.__file__,
    "documents": len(guidance_documents()),
    "uris": [str(item.uri) for item in resources],
    "readable": [bool(list(read_catalog_resource(item.uri))[0].content) for item in resources],
    "intent_manifest": "# snow-kit intent manifest" in intent_manifest,
}
print(json.dumps(payload, sort_keys=True))
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(wheel)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert ".whl/snow_kit/__init__.py" in payload["module"]
    assert payload["documents"] == 3
    assert len(payload["uris"]) == 4
    assert all(payload["readable"])
    assert payload["intent_manifest"] is True
