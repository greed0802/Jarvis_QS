import pytest
import threading
import time
import os
from unittest.mock import MagicMock, patch
import core.ingest_knowledge
from core.ingest_knowledge import process_single_batch, run_incremental_sync

# Set BATCH_SIZE to 1 so that our single-item test batches trigger progress reporting and logging
core.ingest_knowledge.BATCH_SIZE = 1

class MockDoc:
    def __init__(self, page_content, metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}

def test_process_single_batch_success():
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    vs = MagicMock()
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1, 0.2]]
    doc = MockDoc("d1", {"f": "pf"})
    
    res = process_single_batch(1, 2, [doc], vs, emb, 6)
    assert res is True
    assert core.ingest_knowledge.completed_batches == 1
    emb.embed_documents.assert_called_once_with(["d1"])
    vs.add_embeddings.assert_called_once()
    
    # Check add_embeddings args
    args, kwargs = vs.add_embeddings.call_args
    text_embeddings = args[0]
    metadatas = kwargs.get("metadatas", [])
    assert len(text_embeddings) == 1
    assert text_embeddings[0] == ("d1", [0.1, 0.2])
    assert metadatas[0] == {"f": "pf"}

def test_process_single_batch_retry_success():
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    vs = MagicMock()
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    calls = []
    def side_effect(*a, **kw):
        calls.append(a)
        if len(calls) < 3: raise Exception("write failed")
    vs.add_embeddings.side_effect = side_effect
    with patch("time.sleep") as m_sleep:
        res = process_single_batch(1, 2, [MockDoc("d1")], vs, emb, 6)
        assert res is True
        assert len(calls) == 3
        assert m_sleep.call_count == 2

def test_process_single_batch_permanent_failure():
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    vs = MagicMock()
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    vs.add_embeddings.side_effect = Exception("fatal")
    with patch("time.sleep") as m_sleep:
        res = process_single_batch(1, 2, [MockDoc("d1")], vs, emb, 6)
        assert res is False
        assert vs.add_embeddings.call_count == 6

def test_process_single_batch_bisection_trigger():
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    vs = MagicMock()
    emb = MagicMock()
    emb.embed_documents.side_effect = lambda texts: [[0.1]] * len(texts)
    
    # First call (length 2 batch) raises "too many tokens" immediately, triggering bisection.
    # The subsequent calls (length 1 batches) succeed.
    calls = []
    def side_effect(*a, **kw):
        text_embeddings = a[0] if a else kw.get("text_embeddings", [])
        calls.append(len(text_embeddings))
        if len(text_embeddings) == 2:
            raise Exception("too many tokens overall error")
        return None
    vs.add_embeddings.side_effect = side_effect
    
    doc1 = MockDoc("d1", {"f": "pf1"})
    doc2 = MockDoc("d2", {"f": "pf2"})
    
    res = process_single_batch(1, 1, [doc1, doc2], vs, emb, 6)
    assert res is True
    # Verify it made 3 add_embeddings attempts: 1 with 2 items (failed), 2 with 1 item each (succeeded)
    assert len(calls) == 3
    assert calls[0] == 2
    assert calls[1] == 1
    assert calls[2] == 1

@patch("core.ingest_knowledge.load_tracker")
@patch("core.ingest_knowledge.get_safe_path")
@patch("os.walk")
@patch("os.path.getmtime")
@patch("os.path.exists")
def test_run_incremental_sync_no_new_files(
    m_exists, m_mtime, m_walk, m_safe, m_tracker
):
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    m_tracker.return_value = {"D:/knowledge_inbox/test.pdf": 12345.0}
    m_safe.side_effect = lambda p: p
    m_walk.return_value = [("D:/knowledge_inbox", [], ["test.pdf"])]
    m_mtime.return_value = 12345.0
    m_exists.return_value = False

    with pytest.raises(SystemExit) as excinfo:
        run_incremental_sync()
    assert excinfo.value.code == 0

@patch("core.ingest_knowledge.load_tracker")
@patch("core.ingest_knowledge.save_tracker")
@patch("core.ingest_knowledge.get_safe_path")
@patch("os.walk")
@patch("os.path.getmtime")
@patch("core.ingest_knowledge.extract_pdf")
@patch("langchain_community.embeddings.HuggingFaceEmbeddings")
@patch("core.ingest_knowledge.faiss")
@patch("core.ingest_knowledge.FAISS")
@patch("core.ingest_knowledge.InMemoryDocstore")
@patch("os.path.exists")
def test_run_incremental_sync_success(
    m_exists, m_docstore, m_faiss, m_faiss_lib, m_emb, m_pdf, m_mtime, m_walk, m_safe, m_save, m_tracker
):
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    m_exists.return_value = False
    m_tracker.return_value = {}
    m_safe.side_effect = lambda p: p
    m_walk.return_value = [("D:/knowledge_inbox", [], ["test.pdf"])]
    m_mtime.return_value = 12345.0
    m_pdf.return_value = "This is a test document with lots of content. " * 50

    vs = MagicMock()
    m_faiss.return_value = vs
    m_faiss.from_texts.return_value = vs
    m_faiss_lib.IndexFlatL2.return_value = MagicMock()
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    m_emb.return_value = emb

    res = run_incremental_sync()
    assert "Successfully synced and indexed" in res
    assert vs.add_embeddings.called or m_faiss.from_texts.called
    assert m_pdf.called



def test_checkpoint_load_save(tmp_path):
    import core.ingest_knowledge
    import json
    
    test_file = tmp_path / "test_checkpoint.json"
    if test_file.exists():
        try:
            test_file.unlink()
        except Exception:
            pass

    with patch("core.ingest_knowledge.CHECKPOINT_FILE", str(test_file)):
        try:
            # Initially empty
            assert core.ingest_knowledge.load_checkpoint() == set()
            
            # Save a batch
            core.ingest_knowledge.save_batch_checkpoint(1)
            assert core.ingest_knowledge.load_checkpoint() == {1}
            
            # Save another batch
            core.ingest_knowledge.save_batch_checkpoint(3)
            assert core.ingest_knowledge.load_checkpoint() == {1, 3}
        finally:
            if test_file.exists():
                try:
                    test_file.unlink()
                except Exception:
                    pass


@patch("core.ingest_knowledge.load_tracker")
@patch("core.ingest_knowledge.save_tracker")
@patch("core.ingest_knowledge.get_safe_path")
@patch("os.walk")
@patch("os.path.getmtime")
@patch("core.ingest_knowledge.extract_pdf")
@patch("core.ingest_knowledge.load_checkpoint")
@patch("langchain_community.embeddings.HuggingFaceEmbeddings")
@patch("core.ingest_knowledge.faiss")
@patch("core.ingest_knowledge.FAISS")
@patch("core.ingest_knowledge.InMemoryDocstore")
@patch("os.path.exists")
@patch("os.remove")
def test_run_incremental_sync_checkpoint_integration(
    m_remove, m_exists, m_docstore, m_faiss, m_faiss_lib, m_emb, m_checkpoint, m_pdf, m_mtime, m_walk, m_safe, m_save, m_tracker
):
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    m_exists.side_effect = lambda p: "batch_checkpoint.json" in str(p)
    m_tracker.return_value = {}
    m_safe.side_effect = lambda p: p

    # 3 mock files -> will be read as 3 documents by standard sync loop
    m_walk.return_value = [("D:/knowledge_inbox", [], ["doc1.pdf", "doc2.pdf", "doc3.pdf"])]
    m_mtime.return_value = 12345.0
    m_pdf.return_value = "This is a document content that is long enough to pass."

    # Checkpoint registers batch 1 and 2 as completed
    m_checkpoint.return_value = {1, 2}

    vs = MagicMock()
    m_faiss.load_local.return_value = vs
    m_faiss.return_value = vs
    m_faiss.from_texts.return_value = vs
    m_faiss_lib.IndexFlatL2.return_value = MagicMock()

    # Mock embeddings to embed lists correctly
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    m_emb.return_value = emb

    res = run_incremental_sync()
    assert "Successfully synced and indexed" in res

    # Batch 1 and 2 were skipped. Only batch 3 is pending.
    # The integration test validates successful completion with checkpoint recovery
    assert vs.add_embeddings.call_count == 1 or m_faiss.from_texts.call_count == 1

    # Since failed_batches == 0, checkpoint file should be cleaned up (removed)
    m_remove.assert_called_once_with(core.ingest_knowledge.CHECKPOINT_FILE)


def test_process_single_batch_rate_limit_retry():
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    vs = MagicMock()
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    calls = []
    def side_effect(*a, **kw):
        calls.append(a)
        if len(calls) < 3: raise Exception("rate limit 429")
    vs.add_embeddings.side_effect = side_effect
    with patch("time.sleep") as m_sleep:
        res = process_single_batch(1, 2, [MockDoc("d1")], vs, emb, 6)
        assert res is True
        assert len(calls) == 3
        # Rate limit uses 15 * attempt waits: 15, 30
        assert m_sleep.call_count == 2
        m_sleep.assert_any_call(15)
        m_sleep.assert_any_call(30)


def test_process_single_batch_rate_limit_permanent_failure():
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    vs = MagicMock()
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    vs.add_embeddings.side_effect = Exception("rate limit 429")
    with patch("time.sleep") as m_sleep:
        res = process_single_batch(1, 2, [MockDoc("d1")], vs, emb, 6)
        assert res is False
        # Should attempt 6 times before giving up
        assert vs.add_embeddings.call_count == 6
        # Verify exponential backoff: 15, 30, 45, 60, 75
        assert m_sleep.call_count == 5
        m_sleep.assert_any_call(15)
        m_sleep.assert_any_call(30)
        m_sleep.assert_any_call(45)
        m_sleep.assert_any_call(60)
        m_sleep.assert_any_call(75)


@patch("core.ingest_knowledge.load_tracker")
@patch("langchain_community.embeddings.HuggingFaceEmbeddings")
@patch("core.ingest_knowledge.faiss")
@patch("core.ingest_knowledge.FAISS")
@patch("core.ingest_knowledge.InMemoryDocstore")
@patch("os.path.exists")
@patch("builtins.open")
@patch("pickle.load")
@patch("os.remove")
def test_run_incremental_sync_loading_from_staging(
    m_remove, m_pickle_load, m_open, m_exists, m_docstore, m_faiss, m_faiss_lib, m_emb, m_tracker
):
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    
    # We want os.path.exists(STAGING_FILE) to be True, other exists to be False
    m_exists.side_effect = lambda p: "staging_chunks.pkl" in str(p) or "inbox" in str(p)
    
    m_tracker.return_value = {}
    
    # Mock pickled documents
    loaded_chunks = [MockDoc("restored content", {"filename": "doc1.pdf", "category": ".", "file_type": ".pdf"})]
    loaded_tracker_data = {"D:/knowledge_inbox/doc1.pdf": 12345.0}
    loaded_files_to_process = ["D:/knowledge_inbox/doc1.pdf"]
    m_pickle_load.return_value = (loaded_chunks, loaded_tracker_data, loaded_files_to_process)
    
    vs = MagicMock()
    m_faiss.return_value = vs
    m_faiss.load_local.return_value = vs
    m_faiss.from_texts.return_value = vs
    m_faiss_lib.IndexFlatL2.return_value = MagicMock()
    
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    emb.embed_query.return_value = [0.1]
    m_emb.return_value = emb
    
    # Run sync
    res = run_incremental_sync()
    
    # Assert
    assert "Successfully synced and indexed" in res
    assert m_pickle_load.called
    assert m_remove.called # because success removes STAGING_FILE


@patch("core.ingest_knowledge.load_tracker")
@patch("core.ingest_knowledge.get_safe_path")
@patch("os.walk")
@patch("os.path.getmtime")
@patch("core.ingest_knowledge.extract_pdf")
@patch("langchain_community.embeddings.HuggingFaceEmbeddings")
@patch("core.ingest_knowledge.faiss")
@patch("core.ingest_knowledge.FAISS")
@patch("core.ingest_knowledge.InMemoryDocstore")
@patch("os.path.exists")
@patch("builtins.open")
@patch("pickle.dump")
@patch("os.remove")
@patch("time.sleep")
def test_run_incremental_sync_saving_staging_on_failure(
    m_sleep, m_remove, m_pickle_dump, m_open, m_exists, m_docstore, m_faiss, m_faiss_lib, m_emb, m_pdf, m_mtime, m_walk, m_safe, m_tracker
):
    import core.ingest_knowledge
    core.ingest_knowledge.completed_batches = 0
    
    # staging doesn't exist
    m_exists.return_value = False
    
    m_tracker.return_value = {}
    m_safe.side_effect = lambda p: p
    m_walk.return_value = [("D:/knowledge_inbox", [], ["test.pdf"])]
    m_mtime.return_value = 12345.0
    m_pdf.return_value = "This is a test document content that is long enough to pass."
    
    vs = MagicMock()
    # Mock embed_documents or add_embeddings to FAIL, simulating embedding failure
    vs.add_embeddings.side_effect = Exception("Ollama connection error")
    m_faiss.return_value = vs
    m_faiss.from_texts.side_effect = Exception("Ollama connection error")
    m_faiss_lib.IndexFlatL2.return_value = MagicMock()
    
    emb = MagicMock()
    emb.embed_documents.return_value = [[0.1]]
    emb.embed_query.return_value = [0.1]
    m_emb.return_value = emb
    
    # Run sync
    res = run_incremental_sync()
    
    # Assert
    assert "Finished with" in res # failed batches scenario
    assert m_pickle_dump.called # staging file was saved!
    
    # Staging file is NOT removed on failure (since failed_batches > 0)
    staging_file_removed = any("staging_chunks.pkl" in str(arg[0]) for arg in m_remove.call_args_list if arg)
    assert not staging_file_removed


def test_extract_excel_csv():
    import pandas as pd
    from core.ingest_knowledge import extract_excel
    from pathlib import Path

    csv_data = pd.DataFrame({
        "Col1": ["Val1", None, "Val3"],
        "Col2": ["Val2", "Val4", "nan"],
        "Col3": [None, None, None]
    })
    
    with patch("pandas.read_csv") as mock_read:
        mock_read.return_value = csv_data
        result = extract_excel(Path("test_file.csv"))
        assert "--- CSV: test_file ---" in result
        assert "Val1 | Val2" in result or "Col1 | Col2" in result
        assert "Val4" in result
        assert "Val3" in result
        assert "None" not in result
        # Check empty column Col3 is dropped (dropna(axis=1, how='all'))
        assert " |  | " not in result


def test_extract_excel_xlsx():
    import pandas as pd
    from core.ingest_knowledge import extract_excel
    from pathlib import Path

    sheet_data = pd.DataFrame({
        "Item": ["Concrete", "Steel"],
        "Qnty": [150.0, 32.5],
        "Unit": ["m3", "t"]
    })
    
    with patch("pandas.ExcelFile") as mock_excel_file:
        mock_xl = MagicMock()
        mock_xl.sheet_names = ["Sheet1"]
        mock_xl.parse.return_value = sheet_data
        mock_excel_file.return_value = mock_xl
        
        # Test lowercase
        res_lc = extract_excel(Path("test_file.xlsx"))
        assert "--- Sheet: Sheet1 ---" in res_lc
        assert "Concrete | 150.0 | m3" in res_lc
        assert "Steel | 32.5 | t" in res_lc
        
        # Test mixed case
        res_mc = extract_excel(Path("test_file.xlsX"))
        assert "--- Sheet: Sheet1 ---" in res_mc
        assert "Concrete | 150.0 | m3" in res_mc

        # Test uppercase
        res_uc = extract_excel(Path("test_file.XLSX"))
        assert "--- Sheet: Sheet1 ---" in res_uc
        assert "Concrete | 150.0 | m3" in res_uc


def test_parse_costx_excel_calamine_failure():
    from core.ingest_knowledge import extract_excel
    from pathlib import Path
    
    with patch("pandas.ExcelFile") as mock_excel_file:
        # Calamine/ExcelFile fails with Exception
        mock_excel_file.side_effect = Exception("Calamine engine failed")
        
        res = extract_excel(Path("corrupted_costx.xlsx"))
        assert res == ""
        mock_excel_file.assert_called_once_with("corrupted_costx.xlsx", engine='calamine')


def test_parse_any_document_txt_md(tmp_path):
    from core.ingest_knowledge import parse_any_document
    
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Hello Text File World\nQuantity Surveying Notes", encoding="utf-8")
    
    md_file = tmp_path / "test.md"
    md_file.write_text("# Markdown Title\n- Item 1\n- Item 2", encoding="utf-8")
    
    res_txt = parse_any_document(str(txt_file))
    res_md = parse_any_document(str(md_file))
    
    assert "Hello Text File World" in res_txt
    assert "Quantity Surveying Notes" in res_txt
    assert "Markdown Title" in res_md
    assert "- Item 1" in res_md


def test_parse_any_document_eml(tmp_path):
    from core.ingest_knowledge import parse_any_document
    
    eml_content = (
        "Subject: RFI-001 Concrete Specs\n"
        "From: engineer@project.com\n"
        "To: qs@project.com\n"
        "Date: Mon, 17 Aug 2026 10:00:00 +0000\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        "Please find the concrete specifications attached for the RFI response.\n"
    ).encode("utf-8")
    
    eml_file = tmp_path / "rfi.eml"
    eml_file.write_bytes(eml_content)
    
    res = parse_any_document(str(eml_file))
    assert "Subject: RFI-001 Concrete Specs" in res
    assert "From: engineer@project.com" in res
    assert "To: qs@project.com" in res
    assert "Date: Mon, 17 Aug 2026 10:00:00 +0000" in res
    assert "Please find the concrete specifications" in res


def test_parse_any_document_tsv(tmp_path):
    from core.ingest_knowledge import parse_any_document
    
    tsv_content = (
        "Item\tQuantity\tUnit\n"
        "Excavation\t1000\tm3\n"
        "Brickwork\t250\tm2\n"
    )
    
    tsv_file = tmp_path / "rates.tsv"
    tsv_file.write_text(tsv_content, encoding="utf-8")
    
    res = parse_any_document(str(tsv_file))
    assert "--- Table: rates.tsv ---" in res
    assert "Excavation | 1000 | m3" in res
    assert "Brickwork | 250 | m2" in res


def test_extract_docx_tables_mock():
    from core.ingest_knowledge import extract_docx
    from pathlib import Path
    
    mock_doc = MagicMock()
    mock_p1 = MagicMock()
    mock_p1.text = "Paragraph Text"
    mock_doc.paragraphs = [mock_p1]
    
    mock_cell_1 = MagicMock()
    mock_cell_1.text = "Header 1"
    mock_cell_2 = MagicMock()
    mock_cell_2.text = "Header 2"
    
    mock_row = MagicMock()
    mock_row.cells = [mock_cell_1, mock_cell_2]
    
    mock_table = MagicMock()
    mock_table.rows = [mock_row]
    mock_doc.tables = [mock_table]
    
    with patch("docx.Document", return_value=mock_doc):
        res = extract_docx(Path("dummy.docx"))
        assert "Paragraph Text" in res
        assert "Header 1 | Header 2" in res


def test_openpyxl_named_cell_style_patch():
    try:
        from openpyxl.styles.named_styles import NamedCellStyle
    except ImportError:
        from openpyxl.styles.named_styles import _NamedCellStyle as NamedCellStyle

    # Verify that instantiating NamedCellStyle with name=None uses recover style name
    style_none = NamedCellStyle(name=None, xfId=0)
    assert style_none.name == "CostX_Recovered_Style"

    # Verify that custom style names are preserved
    style_custom = NamedCellStyle(name="CustomStyle", xfId=1)
    assert style_custom.name == "CustomStyle"
