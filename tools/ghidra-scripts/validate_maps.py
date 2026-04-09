# Validate reverse-engineering maps and export manifest.
#
# Checks:
#   - duplicate entry_va rows in functions.csv
#   - non-ASCII bytes in any CSV under reverse-engineering/maps/
#   - binary-layout.ini function refs that are missing from functions.csv
#   - inferred functions that could be promoted to verified
#   - manifest.csv rows whose export_status is not ok
#
# Usage:
#   -postScript .../validate_maps.py
#   -postScript .../validate_maps.py --maps=C:\path\to\maps
# @category: Analysis

import csv
import os
import re

FUNCTION_ADDRESS_KEYS = set([
    "builder", "logic", "renderer", "handler", "header_renderer",
    "hint_renderer", "owner", "keyboard_edge_helper", "backend_dispatcher",
])

REQUIRED_FUNCTION_COLUMNS = [
    "entry_va", "rva", "subsystem", "symbol_name", "kind",
    "calling_convention", "signature_note", "status", "export", "source", "notes",
]


def get_repo_root():
    script_dir = os.path.dirname(getSourceFile().getAbsolutePath())
    return os.path.dirname(os.path.dirname(script_dir))


def get_default_paths():
    repo_root = get_repo_root()
    re_root = os.path.join(repo_root, "..", "Decompiled Game", "reverse-engineering")
    maps_dir = os.path.join(re_root, "maps")
    return {
        "maps_dir": os.path.abspath(maps_dir),
        "functions_csv": os.path.abspath(os.path.join(maps_dir, "functions.csv")),
        "binary_layout_ini": os.path.abspath(os.path.join(repo_root, "config", "binary-layout.ini")),
        "manifest_csv": os.path.abspath(os.path.join(re_root, "pseudo-source", "manifest.csv")),
    }


def parse_args():
    defaults = get_default_paths()
    paths = dict(defaults)

    args = [arg.strip() for arg in getScriptArgs() if arg.strip()]
    for arg in args:
        if arg.startswith("--maps="):
            maps_dir = os.path.abspath(arg.split("=", 1)[1])
            paths["maps_dir"] = maps_dir
            paths["functions_csv"] = os.path.join(maps_dir, "functions.csv")
        elif arg.startswith("--functions="):
            paths["functions_csv"] = os.path.abspath(arg.split("=", 1)[1])
        elif arg.startswith("--binary-layout="):
            paths["binary_layout_ini"] = os.path.abspath(arg.split("=", 1)[1])
        elif arg.startswith("--manifest="):
            paths["manifest_csv"] = os.path.abspath(arg.split("=", 1)[1])
    return paths


def normalize_va(text):
    try:
        return "0x%08X" % int(text.strip(), 16)
    except Exception:
        return None


def scan_non_ascii(path):
    handle = open(path, "rb")
    try:
        raw = handle.read()
    finally:
        handle.close()

    issues = []
    line_no = 1
    col_no = 1
    for ch in raw:
        if ord(ch) > 0x7f:
            issues.append((line_no, col_no, ord(ch)))
            if len(issues) >= 10:
                break
        if ch == "\n":
            line_no += 1
            col_no = 1
        else:
            col_no += 1
    return issues


def main():
    paths = parse_args()
    errors = []
    warnings = []

    print("=== VALIDATE MAPS ===")
    for key in sorted(paths.keys()):
        print("%s = %s" % (key, paths[key]))
    print()

    # 1. Check all CSVs for non-ASCII
    maps_dir = paths["maps_dir"]
    if os.path.isdir(maps_dir):
        for name in sorted(os.listdir(maps_dir)):
            if name.lower().endswith(".csv"):
                csv_path = os.path.join(maps_dir, name)
                non_ascii = scan_non_ascii(csv_path)
                for line_no, col_no, value in non_ascii:
                    errors.append("ERROR: non-ASCII byte 0x%02X in %s line %d col %d" %
                                  (value, name, line_no, col_no))

    # 2. Check functions.csv for duplicates
    func_path = paths["functions_csv"]
    functions_by_va = {}
    if os.path.exists(func_path):
        handle = open(func_path, "rb")
        try:
            reader = csv.DictReader(handle)
            line_num = 1
            for row in reader:
                line_num += 1
                entry_va = normalize_va((row.get("entry_va") or "").strip())
                if entry_va is None:
                    continue
                if entry_va in functions_by_va:
                    errors.append("ERROR: duplicate entry_va %s in functions.csv (lines %d and %d)" %
                                  (entry_va, functions_by_va[entry_va]["line"], line_num))
                else:
                    functions_by_va[entry_va] = {"row": row, "line": line_num}
        finally:
            handle.close()

    # 3. Check binary-layout.ini refs against functions.csv
    ini_path = paths["binary_layout_ini"]
    missing_refs = []
    if os.path.exists(ini_path):
        handle = open(ini_path, "rb")
        try:
            ini_text = handle.read().decode("latin-1")
        finally:
            handle.close()

        section = "<root>"
        for line_no, raw_line in enumerate(ini_text.splitlines(), 1):
            line = raw_line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            if "=" not in line:
                continue
            key = line.split("=", 1)[0].strip().lower()
            value = line.split("=", 1)[1].strip()
            if key not in FUNCTION_ADDRESS_KEYS:
                continue
            for match in re.finditer(r"0x[0-9a-fA-F]{8}", value):
                va = normalize_va(match.group(0))
                if va and va not in functions_by_va:
                    missing_refs.append("[%s] %s = %s (line %d)" % (section, key, va, line_no))

    # 4. Check manifest for non-ok exports
    manifest_path = paths["manifest_csv"]
    manifest_issues = []
    if os.path.exists(manifest_path):
        handle = open(manifest_path, "rb")
        try:
            reader = csv.DictReader(handle)
            for row in reader:
                status = (row.get("export_status") or "").strip()
                if status != "ok":
                    manifest_issues.append("WARN: export_status=%s for %s (%s)" %
                                           (status, (row.get("entry_va") or "").strip(),
                                            (row.get("symbol_name") or "").strip()))
        finally:
            handle.close()

    # 5. Check inferred functions that could be promoted
    promotable = []
    for va in sorted(functions_by_va.keys()):
        entry = functions_by_va[va]
        row = entry["row"]
        if (row.get("status") or "").strip().lower() != "inferred":
            continue
        addr = toAddr(va)
        func = getFunctionAt(addr)
        if func is not None:
            promotable.append("%s %s (function exists in Ghidra)" %
                              (va, (row.get("symbol_name") or "").strip()))

    # Report
    if errors:
        print("=== ERRORS ===")
        for e in errors:
            print(e)
        print()

    print("=== MISSING FROM FUNCTIONS.CSV ===")
    if missing_refs:
        for ref in missing_refs:
            print("WARN: %s" % ref)
    else:
        print("NONE")
    print()

    print("=== MANIFEST ISSUES ===")
    if manifest_issues:
        for issue in manifest_issues:
            print(issue)
    else:
        print("NONE")
    print()

    print("=== PROMOTABLE INFERRED ===")
    if promotable:
        for p in promotable:
            print("PROMOTE: %s" % p)
    else:
        print("NONE")
    print()

    print("=== SUMMARY ===")
    print("FUNCTION_ROWS %d" % len(functions_by_va))
    print("BINARY_LAYOUT_MISSING %d" % len(missing_refs))
    print("MANIFEST_ISSUES %d" % len(manifest_issues))
    print("PROMOTABLE %d" % len(promotable))
    print("ERRORS %d" % len(errors))

    if errors:
        raise SystemExit(1)


main()
