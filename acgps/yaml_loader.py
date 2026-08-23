from __future__ import annotations

import re
from typing import Any

import yaml


ANCHOR_OR_ALIAS_RE = re.compile(r"(^|[\s\[{,])([&*])[A-Za-z0-9_.-]+")


class StrictYamlError(ValueError):
    pass


class DuplicateYamlKeyError(StrictYamlError):
    def __init__(self, key: object, *, mark: object | None = None) -> None:
        location = ""
        if mark is not None and hasattr(mark, "line") and hasattr(mark, "column"):
            location = f" at line {mark.line + 1}, column {mark.column + 1}"
        super().__init__(f"duplicate YAML key {key!r}{location}")
        self.key = key
        self.mark = mark


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateYamlKeyError(key, mark=getattr(key_node, "start_mark", None))
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def contains_yaml_anchor_or_alias(text: str) -> bool:
    return bool(ANCHOR_OR_ALIAS_RE.search(text))


def load_yaml_strict(text: str, *, logical_path: str) -> Any:
    if contains_yaml_anchor_or_alias(text):
        raise StrictYamlError(f"{logical_path}: YAML aliases and anchors are not allowed")
    try:
        return yaml.load(text, Loader=UniqueKeyLoader)
    except StrictYamlError:
        raise
    except yaml.YAMLError as exc:
        raise StrictYamlError(f"{logical_path}: malformed YAML: {exc}") from exc
