"""Unit tests for spreadsheet tool functions"""
import unittest
from core.spreadsheet_tool import (
    query_project_spreadsheets,
    is_quantitative_query,
    extract_project_name,
    find_project_dir_by_name,
    locate_excel_files,
    tokenize,
    QUANTITATIVE_KEYWORDS,
    CONCEPTUAL_KEYWORDS
)


class TestSpreadsheetTool(unittest.TestCase):
    
    def test_tokenize(self):
        self.assertEqual(tokenize("Monarch Place"), ["monarch", "place"])
        self.assertEqual(tokenize("horsley_drive"), ["horsley", "drive"])
        self.assertEqual(tokenize("1403-Horsley-Drive"), ["1403", "horsley", "drive"])
    
    def test_is_quantitative_query(self):
        # Quantitative queries should return True
        self.assertTrue(is_quantitative_query("What is the reinforcement tonnage?"))
        self.assertTrue(is_quantitative_query("steel tonnage for Monarch Place"))
        self.assertTrue(is_quantitative_query("reinforcement schedule"))
        self.assertTrue(is_quantitative_query("pile quantity"))
        self.assertTrue(is_quantitative_query("BoQ rates"))
        
        # Conceptual queries should return False
        self.assertFalse(is_quantitative_query("What is the specification for reinforcement?"))
        self.assertFalse(is_quantitative_query("concrete specification"))
        self.assertFalse(is_quantitative_query("contract clause for steel"))
        self.assertFalse(is_quantitative_query("standard compliance"))
        
        # Mixed - conceptual should override
        self.assertFalse(is_quantitative_query("specification for reinforcement tonnage"))
    
    def test_extract_project_name(self):
        # Monarch Place
        result = extract_project_name("What is the reinforcement tonnage for Monarch Place?")
        self.assertEqual(result, "monarch_place")
        
        # horsley drive (with underscore in folder)
        result = extract_project_name("reinforcement schedule for horsley drive")
        self.assertEqual(result, "horsley_drive")
        
        # Non-existent project
        result = extract_project_name("reinforcement for nonexistent project")
        self.assertIsNone(result)
    
    def test_find_project_dir_by_name(self):
        # Monarch Place
        result = find_project_dir_by_name("Monarch Place")
        self.assertIsNotNone(result)
        self.assertTrue("monarch_place" in str(result))
        
        # horsley_drive
        result = find_project_dir_by_name("horsley_drive")
        self.assertIsNotNone(result)
        self.assertTrue("horsley_drive" in str(result))
        
        # horsley drive (with space)
        result = find_project_dir_by_name("horsley drive")
        self.assertIsNotNone(result)
        self.assertTrue("horsley_drive" in str(result))
    
    def test_locate_excel_files(self):
        from pathlib import Path
        project_dir = find_project_dir_by_name("Monarch Place")
        self.assertIsNotNone(project_dir)
        
        files = locate_excel_files(project_dir)
        self.assertGreater(len(files), 0)
        for f in files:
            self.assertTrue(f.suffix.lower() in ['.xlsx', '.xls', '.xlsm'])
    
    def test_query_project_spreadsheets_monarch_reinforcement(self):
        result = query_project_spreadsheets("Monarch Place", ["reinforcement", "tonnage"])
        self.assertIn("SPREADSHEET QUERY RESULTS FOR: monarch_place", result)
        self.assertIn("reinforcement", result.lower())
        self.assertIn("tonnage", result.lower())
        self.assertGreater(len(result), 100)
    
    def test_query_project_spreadsheets_horsley_steel(self):
        result = query_project_spreadsheets("horsley drive", ["steel", "tonnage"])
        self.assertIn("SPREADSHEET QUERY RESULTS FOR: horsley_drive", result)
        self.assertIn("steel", result.lower())
        self.assertGreater(len(result), 100)
    
    def test_quantitative_keywords_present(self):
        # Verify key quantitative keywords are in the list
        self.assertIn("reinforcement", QUANTITATIVE_KEYWORDS)
        self.assertIn("tonnage", QUANTITATIVE_KEYWORDS)
        self.assertIn("steel", QUANTITATIVE_KEYWORDS)
        self.assertIn("schedule", QUANTITATIVE_KEYWORDS)
        self.assertIn("boq", QUANTITATIVE_KEYWORDS)
        self.assertIn("quantity", QUANTITATIVE_KEYWORDS)
        self.assertIn("rate", QUANTITATIVE_KEYWORDS)
        self.assertIn("pile", QUANTITATIVE_KEYWORDS)
        self.assertIn("pfc", QUANTITATIVE_KEYWORDS)
    
    def test_conceptual_keywords_present(self):
        # Verify key conceptual keywords are in the list
        self.assertIn("specification", CONCEPTUAL_KEYWORDS)
        self.assertIn("clause", CONCEPTUAL_KEYWORDS)
        self.assertIn("contract", CONCEPTUAL_KEYWORDS)
        self.assertIn("standard", CONCEPTUAL_KEYWORDS)
        self.assertIn("compliance", CONCEPTUAL_KEYWORDS)
    def test_rank_excel_files_prioritization(self):
        from pathlib import Path
        from core.spreadsheet_tool import rank_excel_files
        
        files = [
            Path("C:/projects/test/1403 Project Checklist.xlsx"),
            Path("C:/projects/test/1403 Project Reinforcement Schedule.xlsx"),
            Path("C:/projects/test/General Document.xlsx")
        ]
        
        # Query about steel/tonnage should prioritize reinforcement
        tonnage_query_terms = ["steel", "tonnage"]
        ranked_for_tonnage = rank_excel_files(files, tonnage_query_terms)
        self.assertEqual(ranked_for_tonnage[0].name, "1403 Project Reinforcement Schedule.xlsx")
        
        # Query about check/verify should prioritize checklist
        checklist_query_terms = ["check", "checklist"]
        ranked_for_check = rank_excel_files(files, checklist_query_terms)
        self.assertEqual(ranked_for_check[0].name, "1403 Project Checklist.xlsx")

    def test_is_noise_row(self):
        from core.spreadsheet_tool import is_noise_row
        
        # Disclaimer/Boilerplate noise
        self.assertTrue(is_noise_row(["All dimensions to be verified on site.", "", ""]))
        self.assertTrue(is_noise_row(["Copyright 2026", "", ""]))
        
        # UOM == 'Note' noise
        self.assertTrue(is_noise_row(["General Note Item", "Note", ""]))
        self.assertTrue(is_noise_row(["Item description", "Note only", ""]))
        
        # Valid quantitative row should NOT be noise
        self.assertFalse(is_noise_row(["UC Beams size 400", "t", 15.5]))

    def test_get_row_hierarchy(self):
        from core.spreadsheet_tool import get_row_hierarchy
        
        # Build mock table rows
        mock_sheet_rows = [
            ["Structural Works", None, None, None],          # Row 0 - L0 header
            ["Steel Beams", None, None, None],               # Row 1 - L0 header (overwrites structural or adds)
            [None, "Universal Beams (UB)", None, None],       # Row 2 - L1 header
            [None, None, "100 UB 10.5", "10", "t"],          # Row 3 - actual data row
            ["Concrete Works", None, None, None]            # Row 4 - new L0 header
        ]
        
        # Hierarchy for Row 3 should search up and build breadcrumbs
        hierarchy = get_row_hierarchy(mock_sheet_rows, 3)
        self.assertEqual(hierarchy, "[Steel Beams > Universal Beams (UB)] ")



if __name__ == "__main__":
    unittest.main()