"""Comprehensive test of spreadsheet tool across multiple projects and query types"""
from core.spreadsheet_tool import query_project_spreadsheets

tests = [
    ("Monarch Place", ["reinforcement", "tonnage"]),
    ("horsley drive", ["steel", "tonnage"]),
    ("Monarch Place", ["pfc", "beam"]),
    ("horsley drive", ["pile", "quantity"]),
    ("Monarch Place", ["mesh", "fabric"]),
    ("horsley drive", ["rate", "quantity"]),
]

for project, terms in tests:
    result = query_project_spreadsheets(project, terms)
    print(f"=== {project} | {terms} ===")
    print(f"Total chars: {len(result)}")
    print(f"Contains matches: {'Matching rows' in result}")
    # Show first 500 chars
    print(result[:500])
    print()