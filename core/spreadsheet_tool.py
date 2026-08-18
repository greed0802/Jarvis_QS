"""
Dedicated Spreadsheet Query Tool for Quantitative/Tabular Data

Uses python-calamine to query specific project spreadsheets on demand
without FAISS chunk limits. Handles steel tonnages, BoQs, reinforcement
schedules, and other tabular quantity surveying data.
"""

import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from python_calamine import load_workbook, CalamineWorkbook

from core.config import INBOX_PATH
from core.config_manager import load_config

# Keywords that indicate a quantitative/tabular query
QUANTITATIVE_KEYWORDS = [
    "tonnage", "tonnes", "tons", "steel", "reinforcement", "rebar",
    "schedule", "boq", "bill of quantities", "quantity", "quantities",
    "rate", "rates", "pricing", "cost", "costs", "pfc", "uc", "ub",
    "beam", "column", "pile", "piling", "mesh", "fabric", "bar",
    "kg/m3", "kg/m", "weight", "mass", "takeoff", "take-off"
]

# Keywords that indicate a conceptual/descriptive query (should use FAISS)
CONCEPTUAL_KEYWORDS = [
    "specification", "specifications", "spec", "narrative", "clause",
    "contract", "clauses", "standard", "standards", "code", "codes",
    "regulation", "regulations", "compliance", "requirement", "requirements",
    "method", "methodology", "procedure", "process", "workmanship",
    "material", "materials", "quality", "testing", "inspection"
]

def tokenize(text: str) -> list[str]:
    """Normalize and tokenize text for fuzzy matching."""
    cleaned = text.lower().replace('-', ' ').replace('_', ' ')
    cleaned = re.sub(r'[^a-z0-9\s]', '', cleaned)
    return [w for w in cleaned.split() if len(w) > 1]

def fuzzy_match(filename: str, query_tokens: list[str]) -> float:
    """Score how well a filename matches query tokens."""
    fn_tokens = tokenize(filename)
    if not fn_tokens or not query_tokens:
        return 0.0

    matches = 0
    for qt in query_tokens:
        if any(qt == ft or qt in ft for ft in fn_tokens):
            matches += 1
    return matches / len(query_tokens)

def find_project_dir_by_name(project_name: str) -> Optional[Path]:
    """Resolve a project name to its actual directory inside the vault."""
    base_dir = Path(INBOX_PATH) / "projects"
    if not base_dir.exists():
        return None

    # Step 1: Direct child matches
    for child in base_dir.iterdir():
        if child.is_dir() and child.name.lower() == project_name.lower():
            return child

    # Step 2: Recurse 1 level deep (checking directories under code folders like 2507/)
    for code_dir in base_dir.iterdir():
        if not code_dir.is_dir():
            continue
        for proj_dir in code_dir.iterdir():
            if proj_dir.is_dir():
                if proj_dir.name.lower() == project_name.lower():
                    return proj_dir

    # Step 3: Fuzzy matching on dir names
    query_tokens = tokenize(project_name)
    best_match = None
    best_score = 0.0

    for code_dir in base_dir.iterdir():
        if not code_dir.is_dir():
            continue
        for proj_dir in code_dir.iterdir():
            if proj_dir.is_dir():
                score = fuzzy_match(proj_dir.name, query_tokens)
                if score > best_score:
                    best_score = score
                    best_match = proj_dir

    if best_score > 0:
        return best_match
    return None

def locate_excel_files(project_dir: Path) -> list[Path]:
    """
    Recursively find all Excel files in a project directory.
    Supports .xlsx, .xlsX, .xls, .xlsm
    """
    excel_files = []
    for ext in ("*.xlsx", "*.xlsX", "*.xls", "*.xlsm"):
        excel_files.extend(project_dir.rglob(ext))
    return excel_files

def rank_excel_files(excel_files: list[Path], search_terms: list[str]) -> list[Path]:
    """
    Dynamic file ranking based on search terms.
    Queries containing 'reinforcement', 'steel', 'tonnage', 'rebar', 'mesh' prioritize files with 'reinforcement'.
    Queries containing 'checklist', 'check', 'verify', 'audit' prioritize files with 'checklist'.
    Otherwise, we sort by search terms matching file name.
    """
    search_terms_lower = [t.lower() for t in search_terms]

    has_steel = any(t in search_terms_lower for t in ["steel", "tonnage", "tonnes", "rebar", "mesh", "reinforcement", "pfc", "uc", "ub"])
    has_checklist = any(t in search_terms_lower for t in ["checklist", "check", "verify", "audit", "bulkcheck"])

    def get_score(filepath: Path) -> int:
        name = filepath.name.lower()
        score = 0

        # Intent prioritization
        if has_steel:
            if "reinforcement" in name or "rebar" in name or "steel" in name:
                score += 1000
            if "checklist" in name or "check" in name:
                score -= 100

        if has_checklist:
            if "checklist" in name or "check" in name or "bulkcheck" in name:
                score += 1000
            if "reinforcement" in name:
                score -= 100

        # Term match scoring
        for term in search_terms_lower:
            if term in name:
                score += 100

        # General keyword boosters for folder/filename structure
        if "reinforcement" in name:
            score += 50
        if "checklist" in name:
            score += 40
        if "boq" in name or "bill" in name:
            score += 30
        if "bulkcheck" in name:
            score += 20

        return score

    return sorted(excel_files, key=get_score, reverse=True)

def extract_sheet_preview(sheet, max_rows: int = 5) -> list[list]:
    """
    Extract first N non-empty rows from a sheet for header context.
    Returns list of row lists.
    """
    try:
        rows = sheet.to_python(skip_empty_area=True)
    except Exception:
        return []

    preview = []
    for row in rows:
        if any(cell is not None and str(cell).strip() != "" for cell in row):
            preview.append(row)
            if len(preview) >= max_rows:
                break
    return preview

def get_row_hierarchy(all_rows: list[list], target_row_idx: int) -> str:
    """
    Scans preceding rows to build a hierarchical breadcrumb path for target_row_idx.
    Detects section headers (rows with text in early columns and empty quantitative columns).
    """
    current_headers = {}

    for r_idx in range(min(target_row_idx, len(all_rows))):
        row = all_rows[r_idx]
        if not row:
            continue

        non_empty_indices = [col_idx for col_idx, cell in enumerate(row) if cell is not None and str(cell).strip() != ""]

        if 0 < len(non_empty_indices) <= 2:
            first_val = str(row[non_empty_indices[0]]).strip()
            if first_val and not re.match(r'^\d+(\.\d+)?$', first_val):
                level = non_empty_indices[0]
                if level < 4:
                    current_headers[level] = first_val
                    for lvl in list(current_headers.keys()):
                        if lvl > level:
                            del current_headers[lvl]

    sorted_levels = sorted(current_headers.keys())
    path_parts = [current_headers[lvl] for lvl in sorted_levels]
    if path_parts:
        return "[" + " > ".join(path_parts) + "] "
    return ""

def is_noise_row(row: list) -> bool:
    """Identify boilerplate disclaimers, notes, and other non-quantitative noise."""
    row_str = " ".join(str(cell) if cell is not None else "" for cell in row).strip()
    row_str_lower = row_str.lower()

    noise_patterns = [
        "dimensions to be verified", "do not scale", "this drawing is", "copyright",
        "all measurements", "for information only", "preliminary only", "client name"
    ]
    if any(pat in row_str_lower for pat in noise_patterns):
        return True

    for cell in row:
        if cell is not None:
            cell_str = str(cell).strip().lower()
            if cell_str in ("note", "note only", "note description", "notes:"):
                return True
    return False

def search_sheet_for_terms(sheet, search_terms: list[str], max_hits: int = 100) -> list[dict]:
    """
    Search a sheet for rows containing any of the search terms.
    Returns list of matching row data with hierarchy and raw row index.
    """
    try:
        all_rows = sheet.to_python(skip_empty_area=True)
    except Exception:
        return []

    hits = []
    search_lower = [t.lower() for t in search_terms]

    for row_idx, row in enumerate(all_rows):
        if is_noise_row(row):
            continue

        row_str = " ".join(str(cell) if cell is not None else "" for cell in row).lower()

        if any(term in row_str for term in search_lower):
            hierarchy = get_row_hierarchy(all_rows, row_idx)
            hits.append({
                "row_index": row_idx,
                "hierarchy": hierarchy,
                "row_data": row,
            })
            if len(hits) >= max_hits:
                break

    return hits

def query_project_spreadsheets(project_name: str, search_terms: list[str]) -> str:
    """
    Main entry point: query spreadsheets for a given project.
    """
    cfg = load_config()
    provider = cfg.get("provider_type", "omniroute")

    if provider == "omniroute":
        MAX_TOKENS = 40000
        max_hits = 300
        max_rows_preview = 30
        max_hits_display = 150
    else:
        MAX_TOKENS = 3000
        max_hits = 50
        max_rows_preview = 5
        max_hits_display = 30

    CHARS_PER_TOKEN = 4
    MAX_CHARS = MAX_TOKENS * CHARS_PER_TOKEN

    project_dir = find_project_dir_by_name(project_name)
    if not project_dir:
        return f"No project directory found matching '{project_name}'"

    excel_files = locate_excel_files(project_dir)
    if not excel_files:
        return f"No Excel files found in project '{project_dir.name}'"

    # Prioritize files
    excel_files = rank_excel_files(excel_files, search_terms)

    output_sections = [
        f"=== SPREADSHEET QUERY RESULTS FOR: {project_dir.name} ===",
        f"Search terms: {', '.join(search_terms)}",
        f"Files scanned: {len(excel_files)}",
        ""
    ]

    total_hits = 0
    estimated_chars = 0
    limit_reached = False

    for excel_file in excel_files:
        if limit_reached:
            break

        try:
            wb: CalamineWorkbook = load_workbook(str(excel_file))
        except Exception as e:
            output_sections.append(f"--- ERROR loading {excel_file.name}: {e} ---")
            continue

        file_hits = 0

        for sheet_name in wb.sheet_names:
            if limit_reached:
                break
            try:
                sheet = wb.get_sheet_by_name(sheet_name)
            except Exception:
                continue

            preview = extract_sheet_preview(sheet, max_rows=max_rows_preview)
            if not preview:
                continue

            hits = search_sheet_for_terms(sheet, search_terms, max_hits=max_hits)

            if hits:
                file_hits += len(hits)
                total_hits += len(hits)

                rel_path = excel_file.relative_to(project_dir)
                section = []
                section.append(f"\n--- File: {rel_path} | Sheet: {sheet_name} ---")

                section.append(f"Headers (first {len(preview)} non-empty rows):")
                for i, row in enumerate(preview):
                    section.append(f"  Row {i}: {row}")

                section.append(f"\nMatching rows ({len(hits)} found):")

                # Render hits
                displayed = hits[:max_hits_display]
                for hit in displayed:
                    line = f"  Row {hit['row_index']}: {hit['hierarchy']}{hit['row_data']}"

                    # Accumulate characters and check budget
                    if estimated_chars + len(line) + 50 > MAX_CHARS:
                        section.append(f"  ... [TRUNCATED: Result exceeded token budget system cap of {MAX_TOKENS} tokens] ...")
                        limit_reached = True
                        break

                    section.append(line)
                    estimated_chars += len(line)

                if len(hits) > len(displayed) and not limit_reached:
                    section.append(f"  ... and {len(hits) - len(displayed)} more matches")

                output = "\n".join(section)
                output_sections.append(output)
                estimated_chars += len(output)

                if estimated_chars >= MAX_CHARS:
                    limit_reached = True

        if file_hits == 0 and not limit_reached:
            rel_path = excel_file.relative_to(project_dir)
            output_sections.append(f"\n--- File: {rel_path} ---")
            output_sections.append("No matches found in this file.")

    output_sections.insert(3, f"Total matches across all files: {total_hits}")

    if total_hits == 0:
        output_sections.append("\nNo quantitative data found matching the search terms.")

    return "\n".join(output_sections)

def is_quantitative_query(query: str) -> bool:
    """
    Determine if a query is quantitative/tabular (should use spreadsheet tool)
    vs conceptual/descriptive (should use FAISS).
    """
    query_lower = query.lower()
    has_quantitative = any(kw in query_lower for kw in QUANTITATIVE_KEYWORDS)
    has_conceptual = any(kw in query_lower for kw in CONCEPTUAL_KEYWORDS)

    if has_conceptual:
        return False
    return has_quantitative

def extract_project_name(query: str) -> Optional[str]:
    """
    Attempt to extract a project name from the query.
    Looks for known project identifiers or capitalized phrases.
    """
    clean_query = re.sub(r'[^\w\s]', ' ', query)
    clean_query = clean_query.replace('_', ' ')

    base_dir = Path(INBOX_PATH) / "projects"
    if base_dir.exists():
        for code_dir in base_dir.iterdir():
            if not code_dir.is_dir():
                continue
            for proj_dir in code_dir.iterdir():
                if proj_dir.is_dir():
                    folder_normalized = proj_dir.name.replace('_', ' ').lower()
                    if folder_normalized in clean_query.lower():
                        return proj_dir.name

    words = clean_query.split()
    for i in range(len(words) - 1):
        if words[i][0].isupper() and words[i+1][0].isupper():
            potential = f"{words[i]} {words[i+1]}"
            if find_project_dir_by_name(potential):
                return potential

    return None
