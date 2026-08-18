import unittest
from unittest.mock import patch, MagicMock
from langchain_core.messages import AIMessage
import core.orchestrator

class TestOrchestratorOptimizations(unittest.TestCase):

    def test_embeddings_cached_globally(self):
        """Verify HuggingFaceEmbeddings is pre-instantiated globally"""
        from langchain_community.embeddings import HuggingFaceEmbeddings
        self.assertIsNotNone(core.orchestrator._embeddings_instance)
        self.assertTrue(isinstance(core.orchestrator._embeddings_instance, HuggingFaceEmbeddings))

    @patch("core.orchestrator.run_incremental_sync")
    @patch("core.orchestrator.FAISS")
    @patch("os.path.exists")
    def test_sync_auto_search_chaining(self, mock_exists, mock_faiss, mock_sync):
        """Verify sync_knowledge_vault triggers incremental sync & auto-vector search"""
        mock_exists.return_value = True
        mock_sync.return_value = "Successfully synced workspace files."
        
        # Mock FAISS vectorstore retriever & return docs
        mock_vectorstore = MagicMock()
        mock_retriever = MagicMock()
        mock_doc = MagicMock()
        mock_doc.page_content = "This is a construction rate specification detailed test."
        mock_doc.metadata = {"filename": "rates.xlsx"}
        mock_retriever.invoke.return_value = [mock_doc]
        mock_vectorstore.as_retriever.return_value = mock_retriever
        mock_faiss.load_local.return_value = mock_vectorstore

        # Set the latest user query target
        core.orchestrator.LATEST_USER_QUERY = "what are the construction rates"

        # Import sync_knowledge_vault tool directly
        from core.orchestrator import sync_knowledge_vault as sync_tool
        
        # Invoke sync tool
        result = sync_tool.invoke({})
        
        # Check that increment sync was called
        mock_sync.assert_called_once()
        
        # Check that search query matched the latest query tracking variable
        mock_retriever.invoke.assert_called_with("what are the construction rates")
        
        # Verify the returned content contains both the sync logs and the search results
        self.assertIn("Successfully synced", result)
        self.assertIn("Auto-Search Chaining Results for 'what are the construction rates'", result)
        self.assertIn("rates.xlsx", result)
        self.assertIn("construction rate specification", result)

if __name__ == '__main__':
    unittest.main()
