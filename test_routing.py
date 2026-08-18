"""Test routing logic for quantitative vs conceptual queries"""
from core.orchestrator import is_quantitative_query, extract_project_name

# Test 1: Quantitative query for Monarch Place
q1 = "What is the reinforcement tonnage for Monarch Place?"
print("Query 1:", q1)
print("  is_quantitative:", is_quantitative_query(q1))
print("  project:", extract_project_name(q1))

# Test 2: Conceptual query
q2 = "What is the concrete specification for Monarch Place?"
print("\nQuery 2:", q2)
print("  is_quantitative:", is_quantitative_query(q2))
print("  project:", extract_project_name(q2))

# Test 3: Quantitative query for horsley drive
q3 = "steel tonnage schedule for horsley drive"
print("\nQuery 3:", q3)
print("  is_quantitative:", is_quantitative_query(q3))
print("  project:", extract_project_name(q3))

# Test 4: Quantitative query with PFC
q4 = "PFC beam quantities for Monarch Place"
print("\nQuery 4:", q4)
print("  is_quantitative:", is_quantitative_query(q4))
print("  project:", extract_project_name(q4))

# Test 5: Reinforcement schedule
q5 = "reinforcement schedule for Monarch Place"
print("\nQuery 5:", q5)
print("  is_quantitative:", is_quantitative_query(q5))
print("  project:", extract_project_name(q5))

# Test 6: Mixed - should be conceptual (specification overrides)
q6 = "specification for reinforcement tonnage"
print("\nQuery 6:", q6)
print("  is_quantitative:", is_quantitative_query(q6))

# Test 7: Pile quantities
q7 = "pile quantities for horsley drive"
print("\nQuery 7:", q7)
print("  is_quantitative:", is_quantitative_query(q7))
print("  project:", extract_project_name(q7))