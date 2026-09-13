from __future__ import annotations

import re
from pathlib import Path

import yaml

PLACEHOLDER_WITH_DEFAULT = re.compile(r"\$\{[^:}]+:([^}]*)\}")
PLACEHOLDER_NO_DEFAULT = re.compile(r"\$\{[^}]+\}")

DATASOURCE_URL_KEYS = ("spring.datasource.url", "spring.r2dbc.url")
JDBC_URL_PATTERN = re.compile(r"(?:jdbc|r2dbc):(\w+)://[^/]+/([\w.-]+)")


def _resolve_placeholders(value: str) -> str:
    """Resolve Spring `${VAR:default}` placeholders to their default value.
    A placeholder with no default (`${VAR}`) is left as-is — there's no
    literal to fall back to, and guessing one would misrepresent the config.
    """
    return PLACEHOLDER_WITH_DEFAULT.sub(r"\1", value)


def _load_yaml_documents(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        docs = [doc for doc in yaml.safe_load_all(text) if isinstance(doc, dict)]
    except yaml.YAMLError:
        return []
    return docs


def _merge(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def _load_merged_config(repo_root: Path) -> dict:
    """Merge every `application*.yml`/`.yaml` under `src/main/resources`
    (Spring Boot's standard config location) into one dict. Later files and
    later `---` documents within a file win on conflicting keys — good
    enough for "what does this service connect to", not a substitute for
    reading the actual active-profile config.
    """
    merged: dict = {}
    resources_dir = repo_root / "src" / "main" / "resources"
    if not resources_dir.is_dir():
        return merged
    for path in sorted(resources_dir.glob("application*.y*ml")):
        for doc in _load_yaml_documents(path):
            _merge(merged, doc)
    return merged


def _flatten_dotted(config: dict, dotted_key: str) -> object | None:
    node: object = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def resolve_stream_destinations(repo_root: Path) -> dict[str, str]:
    """Map Spring Cloud Stream binding name -> real topic name, read from
    `spring.cloud.stream.bindings.<name>.destination` in application*.yml.
    A binding with no explicit `destination` is omitted rather than assumed
    to equal its own name — some setups rely on that Spring Cloud Stream
    default, but treating it as certain here would risk inventing a topic
    that doesn't exist under that name on the actual broker.
    """
    config = _load_merged_config(repo_root)
    bindings = _flatten_dotted(config, "spring.cloud.stream.bindings")
    if not isinstance(bindings, dict):
        return {}
    destinations: dict[str, str] = {}
    for name, binding_config in bindings.items():
        if isinstance(binding_config, dict) and isinstance(binding_config.get("destination"), str):
            destinations[name] = binding_config["destination"]
    return destinations


def scan_datasources(repo_root: Path) -> list[dict]:
    """Return `[{"engine": "mysql", "database": "tickets_db"}, ...]` parsed
    from `spring.datasource.url`/`spring.r2dbc.url` in application*.yml.

    Each profile file (`application-dev.yml`, `application-prod.yml`, ...) is
    read independently rather than merged into one "active profile" — Spring
    only ever activates one at a time, but this pipeline has no way to know
    which, and naively merging them (later filename wins) would silently
    report whichever profile happens to sort last as if it were the real
    config. Scanning each file on its own and returning the union is more
    honest: for a project with several local-dev-style profiles pointing at
    the same engine+database, you'll see one entry; for genuinely different
    databases per profile, you'll see all of them.

    `${VAR:default}` placeholders resolve to their default; a placeholder
    with no default leaves that URL unparsed (skipped) rather than guessed.
    """
    resources_dir = repo_root / "src" / "main" / "resources"
    found: list[dict] = []
    if resources_dir.is_dir():
        for path in sorted(resources_dir.glob("application*.y*ml")):
            for doc in _load_yaml_documents(path):
                for dotted_key in DATASOURCE_URL_KEYS:
                    raw = _flatten_dotted(doc, dotted_key)
                    if not isinstance(raw, str):
                        continue
                    resolved = _resolve_placeholders(raw)
                    if PLACEHOLDER_NO_DEFAULT.search(resolved):
                        continue
                    match = JDBC_URL_PATTERN.search(resolved)
                    if match:
                        found.append({"engine": match.group(1), "database": match.group(2)})

    seen = set()
    unique: list[dict] = []
    for item in found:
        key = (item["engine"], item["database"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
