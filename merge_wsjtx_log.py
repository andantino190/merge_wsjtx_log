#!/usr/bin/env python3
"""merge_wsjtx_log: Fetches, deduplicates, sorts, and synchronizes WSJT-X ADIF logs."""

import argparse
import json
import os
import sys
import tempfile
from typing import List

from adif_handler import (
    ADIFFile,
    ADIFRecord,
    build_adif,
    merge_and_deduplicate,
    parse_adif,
    select_oldest_header,
    sort_records,
)
from remote_sync import LogTarget


def load_config(config_path: str) -> List[str]:
    """Loads target list from JSON config file."""
    if not os.path.isfile(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("targets", [])
    except Exception as e:
        print(f"Warning: Failed to load config from {config_path}: {e}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Fetch, deduplicate, sort, and synchronize WSJT-X ADIF log files."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Target log files ([user@]host:path or local path). Defaults to targets in config.json.",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
        help="Path to configuration file (default: config.json in script directory).",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Simulate the merge and show summary without modifying remote or local files.",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Save the merged ADIF file to a local destination path.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating backup copies before overwriting target files.",
    )

    args = parser.parse_args()

    # Determine targets
    target_strings = args.targets
    if not target_strings:
        target_strings = load_config(args.config)

    if not target_strings:
        print("Error: No targets specified on command line or in config file.", file=sys.stderr)
        sys.exit(1)

    targets = [LogTarget(t) for t in target_strings]
    print(f"=== Starting merge_wsjtx_log for {len(targets)} target(s) ===")
    for i, t in enumerate(targets, 1):
        print(f"  [{i}] {t}")

    with tempfile.TemporaryDirectory() as tmpdir:
        adif_files: List[ADIFFile] = []
        all_records: List[ADIFRecord] = []

        # Step 1: Fetch
        print("\n--- Step 1: Fetching log files ---")
        for i, target in enumerate(targets, 1):
            local_fetched = os.path.join(tmpdir, f"target_{i}.adi")
            print(f"Fetching [{i}/{len(targets)}] {target} ...", end=" ", flush=True)
            try:
                mtime = target.fetch(local_fetched)
                with open(local_fetched, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                adif_file = parse_adif(content, mtime=mtime, file_path=target.raw)
                adif_files.append(adif_file)
                all_records.extend(adif_file.records)
                print(f"OK ({len(adif_file.records)} records)")
            except Exception as e:
                print(f"FAILED!\nError fetching {target}: {e}", file=sys.stderr)
                sys.exit(1)

        # Step 2: Merge & Deduplicate
        print("\n--- Step 2: Merging & Deduplicating records ---")
        total_fetched = len(all_records)
        deduped_records, duplicates_removed = merge_and_deduplicate(all_records)

        # Step 3: Sort
        print("Sorting records by QSO_DATE and TIME_ON ascending ...")
        sorted_records = sort_records(deduped_records)

        # Step 4: Select oldest header
        selected_header = select_oldest_header(adif_files)
        merged_adif_content = build_adif(selected_header, sorted_records)

        # Summary
        print("\n================ Merge Summary ================")
        for i, (target, af) in enumerate(zip(targets, adif_files), 1):
            print(f"  Target {i} ({target}): {len(af.records)} records")
        print(f"  Total records fetched : {total_fetched}")
        print(f"  Duplicates eliminated : {duplicates_removed}")
        print(f"  Final unique records  : {len(sorted_records)}")
        if sorted_records:
            first_qso = f"{sorted_records[0].get('QSO_DATE')} {sorted_records[0].get('TIME_ON')}"
            last_qso = f"{sorted_records[-1].get('QSO_DATE')} {sorted_records[-1].get('TIME_ON')}"
            print(f"  QSO date range        : {first_qso} ~ {last_qso}")
        print("===============================================")

        # Save to output file if requested
        if args.output:
            print(f"\nWriting merged ADIF to local file: {args.output}")
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(merged_adif_content)
            print("Successfully saved to output file.")

        if args.dry_run:
            print("\n[DRY-RUN] No remote or local files were modified.")
            sys.exit(0)

        # Prepare merged temporary file for deployment
        local_merged_path = os.path.join(tmpdir, "merged.adi")
        with open(local_merged_path, "w", encoding="utf-8") as f:
            f.write(merged_adif_content)

        # Step 5: Backup
        if not args.no_backup:
            print("\n--- Step 3: Creating backups on targets ---")
            for i, target in enumerate(targets, 1):
                print(f"Backing up [{i}/{len(targets)}] {target} ...", end=" ", flush=True)
                try:
                    bak_path = target.create_backup()
                    print(f"OK ({bak_path})")
                except Exception as e:
                    print(f"FAILED!\nError creating backup for {target}: {e}", file=sys.stderr)
                    print("Aborting synchronization to prevent data loss.", file=sys.stderr)
                    sys.exit(1)
        else:
            print("\n--- Step 3: Skipping backup (--no-backup specified) ---")

        # Step 6: Deploy
        print("\n--- Step 4: Overwriting targets with merged log ---")
        for i, target in enumerate(targets, 1):
            print(f"Deploying to [{i}/{len(targets)}] {target} ...", end=" ", flush=True)
            try:
                target.deploy(local_merged_path)
                print("OK")
            except Exception as e:
                print(f"FAILED!\nError deploying to {target}: {e}", file=sys.stderr)
                sys.exit(1)

        print("\nAll targets synchronized successfully!")


if __name__ == "__main__":
    main()
