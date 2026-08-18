"""Test edge cases for spreadsheet tool"""
from core.spreadsheet_tool import query_project_spreadsheets
from pathlib import Path

# Test 1: Non-existent project
print("=== Non-existent project ===")
result = query_project_spreadsheets("NonExistent Project", ["reinforcement"])
print(result)
print()

# Test 2: Project with no Excel files
print("=== Project with no Excel files ===")
base = Path("D:/knowledge_inbox/projects")
found = False
for code in base.iterdir():
    if code.is_dir():
        for proj in code.iterdir():
            if proj.is_dir():
                excel = list(proj.rglob("*.xlsx")) + list(proj.rglob("*.xls")) + list(proj.rglob("*.xlsm"))
                if len(excel) == 0:
                    print(f"Found: {proj}")
                    result = query_project_spreadsheets(proj.name, ["reinforcement"])
                    print(result[:500])
                    found = True
                    break
    if found:
        break

if not found:
    print("No project directory without Excel files found")