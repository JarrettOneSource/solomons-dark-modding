#!/usr/bin/env python3
"""Generate the LuaLS/EmmyLua `sd` API inventory from native registrations."""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import re
import sys
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "SolomonDarkModLoader" / "src"
DEFAULT_OUTPUT = ROOT / "api" / "lua" / "sd.lua"

FUNCTION_DEFINITION = re.compile(
    r"\b(?:bool|void)\s+(RegisterLua[A-Za-z0-9_]*Bindings)\s*"
    r"\(\s*(?:LoadedLuaMod\*\s+mod|lua_State\*\s+state)\s*\)\s*\{"
)
ROOT_DEFINITION = re.compile(
    r"\bbool\s+RegisterLuaBindings\s*\(\s*LoadedLuaMod\*\s+mod\s*,"
)
ROOT_CALL = re.compile(r"\b(RegisterLua[A-Za-z0-9_]+Bindings)\s*\(\s*mod->state\s*\)\s*;")
TOKEN = re.compile(
    r"(?P<create>lua_createtable\s*\(\s*state\s*,[^;]+;)"
    r"|(?P<function>RegisterFunction\s*\(\s*state\s*,\s*&[A-Za-z0-9_:]+\s*,"
    r"\s*\"(?P<function_name>[a-z0-9_]+)\"\s*\)\s*;)"
    r"|(?P<helper>(?P<helper_name>RegisterLua[A-Za-z0-9_]+Bindings)\s*"
    r"\(\s*state\s*\)\s*;)"
    r"|(?P<setfield>lua_setfield\s*\(\s*state\s*,\s*(?P<stack_index>-[23])\s*,"
    r"\s*\"(?P<namespace>[a-z0-9_]+)\"\s*\)\s*;)"
)


@dataclasses.dataclass(frozen=True)
class RegisteredNamespace:
    name: str
    functions: tuple[str, ...]
    table_id: str


def _strip_cpp_comments(source: str) -> str:
    """Blank C++ comments without changing offsets or quoted strings."""
    stripped = list(source)
    index = 0
    state = "code"
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if character == '"':
                state = "string"
            elif character == "'":
                state = "character"
            elif character == "/" and following == "/":
                stripped[index] = " "
                stripped[index + 1] = " "
                state = "line_comment"
                index += 1
            elif character == "/" and following == "*":
                stripped[index] = " "
                stripped[index + 1] = " "
                state = "block_comment"
                index += 1
        elif state in {"string", "character"}:
            if character == "\\":
                index += 1
            elif (state == "string" and character == '"') or (
                state == "character" and character == "'"
            ):
                state = "code"
        elif state == "line_comment":
            if character == "\n":
                state = "code"
            else:
                stripped[index] = " "
        elif state == "block_comment":
            if character == "*" and following == "/":
                stripped[index] = " "
                stripped[index + 1] = " "
                state = "code"
                index += 1
            elif character != "\n":
                stripped[index] = " "
        index += 1
    return "".join(stripped)


def _find_closing_brace(source: str, opening_index: int) -> int:
    depth = 0
    index = opening_index
    state = "code"
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if character == '"':
                state = "string"
            elif character == "'":
                state = "character"
            elif character == "/" and following == "/":
                state = "line_comment"
                index += 1
            elif character == "/" and following == "*":
                state = "block_comment"
                index += 1
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return index
        elif state in {"string", "character"}:
            if character == "\\":
                index += 1
            elif (state == "string" and character == '"') or (
                state == "character" and character == "'"
            ):
                state = "code"
        elif state == "line_comment":
            if character == "\n":
                state = "code"
        elif state == "block_comment" and character == "*" and following == "/":
            state = "code"
            index += 1
        index += 1
    raise ValueError("registration function has no closing brace")


def _read_registration_bodies() -> tuple[dict[str, str], str]:
    bodies: dict[str, str] = {}
    root_body = ""
    source_paths = sorted(
        path
        for path in SOURCE_ROOT.rglob("*")
        if path.suffix in {".cpp", ".inl"}
    )
    for path in source_paths:
        source = path.read_text(encoding="utf-8")
        searchable_source = _strip_cpp_comments(source)
        for match in FUNCTION_DEFINITION.finditer(searchable_source):
            name = match.group(1)
            if name in bodies:
                raise ValueError(f"duplicate registration definition: {name}")
            opening_index = match.end() - 1
            closing_index = _find_closing_brace(searchable_source, opening_index)
            bodies[name] = searchable_source[opening_index + 1 : closing_index]

        root_match = ROOT_DEFINITION.search(searchable_source)
        if root_match is not None:
            if root_body:
                raise ValueError("duplicate RegisterLuaBindings definition")
            opening_index = searchable_source.find("{", root_match.end())
            closing_index = _find_closing_brace(searchable_source, opening_index)
            root_body = searchable_source[opening_index + 1 : closing_index]

    if not root_body:
        raise ValueError("RegisterLuaBindings definition was not found")
    return bodies, root_body


def discover_bindings() -> list[RegisteredNamespace]:
    bodies, root_body = _read_registration_bodies()
    root_registrations = ROOT_CALL.findall(root_body)
    if not root_registrations:
        raise ValueError("RegisterLuaBindings contains no namespace registrations")

    parsed: dict[str, tuple[list[RegisteredNamespace], list[str]]] = {}
    active: set[str] = set()

    def parse_registration(name: str) -> tuple[list[RegisteredNamespace], list[str]]:
        if name in parsed:
            return parsed[name]
        if name in active:
            raise ValueError(f"recursive Lua registration helper: {name}")
        body = bodies.get(name)
        if body is None:
            raise ValueError(f"missing registration definition: {name}")

        active.add(name)
        namespaces: list[RegisteredNamespace] = []
        functions: list[str] = []
        table_id = f"{name}:implicit"
        table_ordinal = 0
        for match in TOKEN.finditer(body):
            if match.group("create") is not None:
                table_ordinal += 1
                table_id = f"{name}:{table_ordinal}"
                functions = []
            elif match.group("function") is not None:
                function_name = match.group("function_name")
                if function_name in functions:
                    raise ValueError(f"duplicate sd function in {name}: {function_name}")
                functions.append(function_name)
            elif match.group("helper") is not None:
                helper_name = match.group("helper_name")
                helper_namespaces, helper_functions = parse_registration(helper_name)
                if helper_namespaces:
                    namespaces.extend(helper_namespaces)
                for function_name in helper_functions:
                    if function_name in functions:
                        raise ValueError(
                            f"duplicate helper-provided sd function in {name}: {function_name}"
                        )
                    functions.append(function_name)
            else:
                namespace = match.group("namespace")
                if not functions:
                    raise ValueError(f"sd.{namespace} has no registered functions")
                namespaces.append(
                    RegisteredNamespace(namespace, tuple(functions), table_id)
                )
                if match.group("stack_index") == "-2":
                    functions = []
                    table_id = f"{name}:detached:{len(namespaces)}"

        active.remove(name)
        result = (namespaces, functions)
        parsed[name] = result
        return result

    ordered: OrderedDict[str, RegisteredNamespace] = OrderedDict()
    for registration in root_registrations:
        namespaces, loose_functions = parse_registration(registration)
        if loose_functions:
            raise ValueError(
                f"root registration {registration} left unattached functions: "
                + ", ".join(loose_functions)
            )
        for namespace in namespaces:
            if namespace.name in ordered:
                raise ValueError(f"duplicate sd namespace: {namespace.name}")
            ordered[namespace.name] = namespace

    return list(ordered.values())


def _class_name(namespace: str) -> str:
    return "Sd" + "".join(part.capitalize() for part in namespace.split("_")) + "Api"


def render_stub(namespaces: list[RegisteredNamespace]) -> str:
    if not namespaces:
        raise ValueError("cannot render an empty Lua API")

    canonical_by_table: dict[str, RegisteredNamespace] = {}
    for namespace in namespaces:
        existing = canonical_by_table.get(namespace.table_id)
        if existing is None or namespace.name == "draw":
            canonical_by_table[namespace.table_id] = namespace

    function_count = sum(
        len(namespace.functions) for namespace in canonical_by_table.values()
    )
    lines = [
        "---@meta",
        "",
        "-- Generated by tools/generate_lua_api_stubs.py from RegisterLua*Bindings.",
        "-- Do not edit by hand. Runtime documentation defines precise values and shapes.",
        f"-- Inventory: {len(namespaces)} namespaces, {function_count} unique functions.",
        "",
    ]

    local_name_by_table: dict[str, str] = {}
    for table_id, canonical in canonical_by_table.items():
        local_name_by_table[table_id] = f"sd_{canonical.name}"
        lines.append(f"---@class {_class_name(canonical.name)}")
        lines.append(f"local sd_{canonical.name} = {{}}")
        lines.append("")
        for function_name in canonical.functions:
            lines.extend(
                [
                    "---@param ... any",
                    "---@return any",
                    f"function sd_{canonical.name}.{function_name}(...) end",
                    "",
                ]
            )

    lines.append("---@class SdApi")
    for namespace in namespaces:
        canonical = canonical_by_table[namespace.table_id]
        lines.append(f"---@field {namespace.name} {_class_name(canonical.name)}")
    lines.append("---@type SdApi")
    lines.append("sd = {")
    for namespace in namespaces:
        local_name = local_name_by_table[namespace.table_id]
        lines.append(f"    {namespace.name} = {local_name},")
    lines.extend(["}", "", "return sd", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the checked-in stub is stale")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    try:
        rendered = render_stub(discover_bindings())
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.check:
        if not output.is_file():
            print(f"error: generated Lua API stub is missing: {output}", file=sys.stderr)
            return 1
        existing = output.read_text(encoding="utf-8")
        if existing == rendered:
            print(f"Lua API stub is current: {output.relative_to(ROOT)}")
            return 0
        diff = difflib.unified_diff(
            existing.splitlines(),
            rendered.splitlines(),
            fromfile=str(output.relative_to(ROOT)),
            tofile="generated",
            lineterm="",
        )
        print("\n".join(diff), file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Generated {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
