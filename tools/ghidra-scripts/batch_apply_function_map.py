# Apply canonical names and optional calling conventions from
# reverse-engineering/maps/functions.csv to the Ghidra project.
#
# IMPORTANT: This script WRITES to the project. Run it against the SOURCE
# project (not read-only replicas). After running, refresh replicas with:
#   Invoke-GhidraHeadless.ps1 -RefreshReplica -PreparePool
#
# Usage:
#   -postScript .../batch_apply_function_map.py
#   -postScript .../batch_apply_function_map.py C:\path\to\functions.csv
#   -postScript .../batch_apply_function_map.py --dry-run
#   -postScript .../batch_apply_function_map.py --no-cconv
# @category: Analysis

import csv
import os

from ghidra.program.model.symbol import SourceType


REQUIRED_COLUMNS = [
    "entry_va",
    "subsystem",
    "symbol_name",
    "calling_convention",
]


def get_default_csv_path():
    script_dir = os.path.dirname(getSourceFile().getAbsolutePath())
    repo_root = os.path.dirname(os.path.dirname(script_dir))
    return os.path.join(repo_root, "..", "Decompiled Game",
                        "reverse-engineering", "maps", "functions.csv")


def parse_args():
    dry_run = False
    apply_cconv = True
    csv_path = None

    args = [a.strip() for a in getScriptArgs() if a.strip()]
    for arg in args:
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--no-cconv":
            apply_cconv = False
        elif arg.startswith("--csv="):
            csv_path = arg.split("=", 1)[1]
        elif csv_path is None:
            csv_path = arg
        else:
            print("ERROR: unrecognized argument: %s" % arg)
            raise SystemExit(1)

    if csv_path is None:
        csv_path = get_default_csv_path()
    return os.path.abspath(csv_path), dry_run, apply_cconv


def load_rows(csv_path):
    if not os.path.exists(csv_path):
        print("ERROR: functions.csv was not found: %s" % csv_path)
        raise SystemExit(1)

    handle = open(csv_path, "rb")
    try:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            print("ERROR: functions.csv is missing a header row")
            raise SystemExit(1)

        missing = [name for name in REQUIRED_COLUMNS if name not in reader.fieldnames]
        if missing:
            print("ERROR: functions.csv is missing required columns: %s" % ", ".join(missing))
            raise SystemExit(1)

        rows = []
        seen = set()
        for row in reader:
            entry_va = (row.get("entry_va") or "").strip()
            symbol_name = (row.get("symbol_name") or "").strip()
            if not entry_va or not symbol_name:
                continue
            if entry_va in seen:
                continue
            seen.add(entry_va)
            rows.append(row)
        return rows
    finally:
        handle.close()


def normalize_calling_convention(value):
    text = (value or "").strip().lower()
    if not text or text == "unknown":
        return None

    mapping = {
        "cdecl": "__cdecl",
        "__cdecl": "__cdecl",
        "fastcall": "__fastcall",
        "__fastcall": "__fastcall",
        "stdcall": "__stdcall",
        "__stdcall": "__stdcall",
        "thiscall": "__thiscall",
        "__thiscall": "__thiscall",
    }
    return mapping.get(text)


def main():
    csv_path, dry_run, apply_cconv = parse_args()
    rows = load_rows(csv_path)

    renamed_count = 0
    cconv_count = 0
    skip_count = 0
    error_count = 0

    print("=== FUNCTION MAP ===")
    print("CSV_PATH %s" % csv_path)
    print("ROW_COUNT %d" % len(rows))
    print("DRY_RUN %s" % ("yes" if dry_run else "no"))
    print("APPLY_CCONV %s" % ("yes" if apply_cconv else "no"))
    print()

    for row in rows:
        if monitor.isCancelled():
            print("ERROR: cancelled")
            raise SystemExit(1)

        entry_va = row["entry_va"].strip()
        symbol_name = row["symbol_name"].strip()
        subsystem = (row.get("subsystem") or "").strip()
        kind = (row.get("kind") or "").strip()
        addr = toAddr(entry_va)
        func = getFunctionAt(addr)

        if func is None:
            print("SKIP %s %s (no function at address)" % (entry_va, symbol_name))
            skip_count += 1
            continue

        current_name = func.getName()
        if current_name != symbol_name:
            print("RENAME %s -> %s (%s/%s)" % (current_name, symbol_name, subsystem, kind))
            if not dry_run:
                try:
                    func.setName(symbol_name, SourceType.USER_DEFINED)
                    renamed_count += 1
                except Exception as exc:
                    print("  ERROR rename failed: %s" % exc)
                    error_count += 1
        else:
            print("OK %s %s (unchanged)" % (entry_va, symbol_name))

        cconv_name = normalize_calling_convention(row.get("calling_convention"))
        if apply_cconv and cconv_name is not None:
            current_cconv = func.getCallingConventionName()
            if current_cconv != cconv_name:
                print("  CCONV %s -> %s" % (current_cconv, cconv_name))
                if not dry_run:
                    try:
                        func.setCallingConvention(cconv_name)
                        cconv_count += 1
                    except Exception as exc:
                        print("  ERROR calling convention failed: %s" % exc)
                        error_count += 1

    print()
    print("=== SUMMARY ===")
    print("RENAMED %d" % renamed_count)
    print("CALLING_CONVENTIONS_SET %d" % cconv_count)
    print("SKIPPED %d" % skip_count)
    print("ERRORS %d" % error_count)


main()
