"""Test conceptual query fallback to FAISS"""
from core.orchestrator import is_quantitative_query, extract_project_name, _run_vector_search

q = "What is the concrete specification for Monarch Place?"
print("Query:", q)
print("is_quantitative:", is_quantitative_query(q))
project = extract_project_name(q)
print("project:", project)

# Test FAISS vector search (conceptual fallback)
result = _run_vector_search(q, "D:/Jarvis_QS/faiss_data")
print("--- FAISS RESULT (first 2000 chars) ---")
print(result[:2000])