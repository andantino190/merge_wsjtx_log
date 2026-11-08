#!/usr/bin/env python3
"""ADIF (Amateur Data Interchange Format) parser, merger, and serializer for WSJT-X logs."""

import re
from typing import Dict, List, Optional, Tuple


class ADIFRecord:
    """Represents a single ADIF QSO record."""

    def __init__(self, fields: Optional[Dict[str, str]] = None, field_types: Optional[Dict[str, str]] = None, field_order: Optional[List[str]] = None):
        self.fields: Dict[str, str] = {}
        self.field_types: Dict[str, str] = {}
        self.field_order: List[str] = []

        if fields:
            for k, v in fields.items():
                uk = k.upper()
                self.fields[uk] = v
                if uk not in self.field_order:
                    self.field_order.append(uk)
        if field_types:
            for k, v in field_types.items():
                self.field_types[k.upper()] = v
        if field_order:
            self.field_order = [k.upper() for k in field_order]

    def set_field(self, name: str, value: str, field_type: Optional[str] = None):
        uk = name.upper()
        if uk not in self.field_order:
            self.field_order.append(uk)
        self.fields[uk] = value
        if field_type:
            self.field_types[uk] = field_type

    def get(self, name: str, default: str = "") -> str:
        return self.fields.get(name.upper(), default)

    def dedup_key(self) -> Tuple[str, str, str, str, str]:
        """Returns the uniqueness key for QSO deduplication:

        (CALL, QSO_DATE, TIME_ON, BAND_OR_FREQ, MODE)
        """
        call = self.get("CALL").upper().strip()
        qso_date = self.get("QSO_DATE").strip()
        time_on = self.get("TIME_ON").strip()
        band = self.get("BAND").upper().strip()
        freq = self.get("FREQ").strip()
        band_or_freq = band if band else freq
        mode = self.get("MODE").upper().strip()
        return (call, qso_date, time_on, band_or_freq, mode)

    def to_adif(self) -> str:
        """Serializes the record into ADIF format with trailing <eor>."""
        parts = []
        for tag in self.field_order:
            if tag in self.fields:
                val = self.fields[tag]
                ftype = self.field_types.get(tag)
                # ADIF length is count of characters/bytes. Using utf-8 length or char length.
                length = len(val.encode("utf-8"))
                if ftype:
                    parts.append(f"<{tag.lower()}:{length}:{ftype}>{val}")
                else:
                    parts.append(f"<{tag.lower()}:{length}>{val}")
        parts.append("<eor>")
        return " ".join(parts)


class ADIFFile:
    """Represents an ADIF file including its header and records."""

    def __init__(self, header_raw: str = "", records: Optional[List[ADIFRecord]] = None, mtime: float = 0.0, file_path: str = ""):
        self.header_raw = header_raw.strip()
        self.records: List[ADIFRecord] = records or []
        self.mtime = mtime
        self.file_path = file_path

    @property
    def created_timestamp(self) -> Optional[str]:
        """Extracts <CREATED_TIMESTAMP:...> from header if present."""
        m = re.search(r"<created_timestamp:\d+(?::[a-zA-Z])?>([^<\s]+(?:\s+[^<\s]+)?)", self.header_raw, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None


TAG_PATTERN = re.compile(r"<(?P<tag>[a-zA-Z0-9_]+)(?::(?P<len>\d+))?(?::(?P<type>[a-zA-Z]))?>")


def parse_adif(text: str, mtime: float = 0.0, file_path: str = "") -> ADIFFile:
    """Parses full ADIF text into an ADIFFile instance."""
    # Find EOH (case-insensitive)
    eoh_match = re.search(r"<eoh>", text, re.IGNORECASE)
    if eoh_match:
        header_text = text[: eoh_match.end()]
        body_text = text[eoh_match.end() :]
    else:
        header_text = ""
        body_text = text

    records: List[ADIFRecord] = []
    current_record = ADIFRecord()
    pos = 0
    body_len = len(body_text)

    while pos < body_len:
        match = TAG_PATTERN.search(body_text, pos)
        if not match:
            break

        tag = match.group("tag").upper()
        length_str = match.group("len")
        field_type = match.group("type")
        val_start = match.end()

        if tag == "EOR":
            if current_record.fields:
                records.append(current_record)
                current_record = ADIFRecord()
            pos = val_start
            continue

        if tag == "EOH":
            # If extra EOH found in body, ignore and advance
            pos = val_start
            continue

        if length_str is not None:
            length = int(length_str)
            # Read exact length in characters
            # In Python, string slicing handles multi-byte/unicode chars
            # But let's check byte length vs char length if needed. WSJT-X is ASCII/UTF-8.
            # Usually ADIF lengths in WSJT-X match string length.
            val = body_text[val_start : val_start + length]
            current_record.set_field(tag, val, field_type)
            pos = val_start + length
        else:
            # Tag without length (should not normally happen for data fields)
            pos = val_start

    if current_record.fields:
        records.append(current_record)

    return ADIFFile(header_raw=header_text, records=records, mtime=mtime, file_path=file_path)


def select_oldest_header(adif_files: List[ADIFFile]) -> str:
    """Selects the ADIF header with the oldest timestamp."""
    if not adif_files:
        return "WSJT-X ADIF Export<eoh>\n"

    # Filter files that have non-empty headers
    files_with_header = [f for f in adif_files if f.header_raw]
    if not files_with_header:
        return "WSJT-X ADIF Export<eoh>\n"

    def sort_key(f: ADIFFile):
        ts = f.created_timestamp
        # If timestamp found, use it; otherwise fallback to mtime
        return (0 if ts else 1, ts or "", f.mtime)

    sorted_files = sorted(files_with_header, key=sort_key)
    header = sorted_files[0].header_raw
    if not re.search(r"<eoh>", header, re.IGNORECASE):
        header = f"{header}\n<eoh>"
    return header


def merge_and_deduplicate(all_records: List[ADIFRecord]) -> Tuple[List[ADIFRecord], int]:
    """Merges records, deduplicates based on standard QSO key,

    and prioritizes records with more fields.
    Returns (deduplicated_records, duplicates_removed_count).
    """
    merged_map: Dict[Tuple, ADIFRecord] = {}
    duplicates_count = 0

    for rec in all_records:
        key = rec.dedup_key()
        # If record has no call or date, we can't reliably dedup, give unique key
        if not key[0] or not key[1]:
            unique_key = (f"__anon_{id(rec)}__",)
            merged_map[unique_key] = rec
            continue

        if key in merged_map:
            duplicates_count += 1
            existing = merged_map[key]
            # Keep record with more fields, or merge missing fields
            if len(rec.fields) > len(existing.fields):
                # Supplement missing fields from existing into rec
                for f_name, f_val in existing.fields.items():
                    if f_name not in rec.fields:
                        rec.set_field(f_name, f_val, existing.field_types.get(f_name))
                merged_map[key] = rec
            else:
                # Supplement missing fields from rec into existing
                for f_name, f_val in rec.fields.items():
                    if f_name not in existing.fields:
                        existing.set_field(f_name, f_val, rec.field_types.get(f_name))
        else:
            merged_map[key] = rec

    return list(merged_map.values()), duplicates_count


def sort_records(records: List[ADIFRecord]) -> List[ADIFRecord]:
    """Sorts records by QSO_DATE ascending, then TIME_ON ascending."""
    return sorted(records, key=lambda r: (r.get("QSO_DATE", ""), r.get("TIME_ON", "")))


def build_adif(header: str, records: List[ADIFRecord]) -> str:
    """Builds complete ADIF content from header and records."""
    header_clean = header.strip()
    if not re.search(r"<eoh>", header_clean, re.IGNORECASE):
        header_clean += "<eoh>"

    lines = [header_clean]
    for rec in records:
        lines.append(rec.to_adif())
    return "\n".join(lines) + "\n"
