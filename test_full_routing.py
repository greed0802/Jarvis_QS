"""Test full routing logic with spreadsheet search"""
from core.orchestrator import is_quantitative_query, extract_project_name
from core.spreadsheet_tool import QUANTITATIVE_KEYWORDS, query_project_spreadsheets

q = "What is the reinforcement tonnage for Monarch Place?"
print("Query:", q)
print("is_quantitative:", is_quantitative_query(q))
project = extract_project_name(q)
print("project:", project)
terms = [kw for kw in QUANTITATIVE_KEYWORDS if kw in q.lower()]
print("terms:", terms)

# Test spreadsheet search directly
result = query_project_spreadsheets(project, terms)
print("--- SPREADSHEET RESULT ---")
print(result[:3000])