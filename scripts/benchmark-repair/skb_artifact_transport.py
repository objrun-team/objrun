"""Compose the frozen bounded native pipe primitive; no monkeypatch or Docker on import."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import sys
import skb_artifact_task as task

DIRECTORY = Path(__file__).resolve().parent
FROZEN = {
    "jpg_private_ram_executor.py": "c00404ce4700a1702572f1960877ca7ff178b12dd35e01ead356064d469a5e59",
    "jpg_d_storage_profile.py": "0d0b20832d60248605a3e0314aa5e029091c536dc6f80e3bccf5623da1f18c17",
    "jpg_private_ram_profile.py": "00a9f978b9e2ae90d912a7bd48bc522107c6c0db50a6a6c91df5b800df122ee3",
}
COMPONENT_PROTOCOL = "jpg-private-shared-ram-executor-v1-native-command"
DOCKER = Path("D:/Program/resources/bin/docker.exe")
DOCKER_SHA = "00ffff945b67c65aae98dd980621a80ee135ed4e0931b33ca03687caee019713"
DOCKER_HOST = "npipe:////./pipe/dockerDesktopLinuxEngine"
_component = None


def component_pins():
    result = []
    for name, sha in FROZEN.items():
        p = task.pin(DIRECTORY / name)
        task.demand(p["sha256"] == sha, "transport_source", "Frozen bounded transport component changed")
        result.append(p)
    return result


def component():
    global _component
    before = component_pins()
    if _component is None:
        name = "skb_frozen_c004_transport_component"
        spec = importlib.util.spec_from_file_location(name, DIRECTORY / "jpg_private_ram_executor.py")
        value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
        for imported_name, filename in (("storage", "jpg_d_storage_profile.py"), ("ram", "jpg_private_ram_profile.py")):
            task.demand(Path(getattr(getattr(value, imported_name), "__file__")).resolve() == (DIRECTORY / filename).resolve(),
                        "transport_module", "Imported frozen leaf component substituted")
        _component = value
    task.demand(before == component_pins(), "transport_source", "Component changed during import")
    return _component


def bounded_child(argv, env, directory, serial, guard, timeout, cap=1024**2):
    before = component_pins()
    value = component().bounded_child(argv, env, directory, serial, guard, timeout, cap)
    task.demand(before == component_pins(), "transport_source", "Frozen transport source drift")
    return value


def sanitized_environment(layout, storage):
    result = {k: os.environ[k] for k in ("SystemRoot", "WINDIR", "PATH", "PATHEXT") if k in os.environ}
    result.update(storage.native_environment(layout))
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "DOCKER_CONFIG"):
        p = Path(layout["directories"]["tmp"]) / ("docker-" + key.lower())
        storage.ordinary(p.parent, Path(layout["storePhysical"]))
        p.mkdir(exist_ok=True); storage.ordinary(p, Path(layout["storePhysical"])); result[key] = str(p)
    return result

