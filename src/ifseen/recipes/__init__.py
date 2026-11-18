"""Built-in rule files. `ifseen recipes` lists them; `ifseen init <name>` copies one."""

from __future__ import annotations

from importlib import resources

import yaml


def recipe_names() -> list[str]:
    return sorted(
        p.name.removesuffix(".yaml")
        for p in resources.files(__package__).iterdir()
        if p.name.endswith(".yaml")
    )


def recipe_text(name: str) -> str:
    name = name.removesuffix(".yaml")
    if name not in recipe_names():
        raise KeyError(name)
    return resources.files(__package__).joinpath(f"{name}.yaml").read_text()


def recipe_summary(name: str) -> str:
    first = recipe_text(name).splitlines()[0]
    return first.lstrip("# ").strip()


def recipe_data(name: str) -> dict:
    return yaml.safe_load(recipe_text(name))
