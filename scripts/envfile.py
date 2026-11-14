"""Tiny helper to set NAME=value lines in a git-ignored env file without ever printing values."""

from pathlib import Path


def set_values(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    seen: set[str] = set()
    out = []
    for line in lines:
        name = line.split("=", 1)[0].strip()
        if name in values:
            out.append(f"{name}={values[name]}")
            seen.add(name)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)


def has_value(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        k, sep, v = line.partition("=")
        if sep and k.strip() == name and v.strip():
            return True
    return False
