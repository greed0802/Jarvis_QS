import os
import pickle
import re
import time
from pathlib import Path
import warnings
import faiss

# Suppress openpyxl data validation warnings
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

import docx
import openpyxl
import pandas as pd
import pymupdf
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_text_splitters import RecursiveCharacterTextSplitter

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import email
from email import policy

# --- OPENPYXL COSTX STYLE PATCH ---
# Prevents openpyxl from crashing when CostX exports have NoneType style names
import openpyxl
try:
    from openpyxl.styles.named_styles import NamedCellStyle
except ImportError:
    from openpyxl.styles.named_styles import _NamedCellStyle as NamedCellStyle

_original_named_cell_style_init = NamedCellStyle.__init__

def _patched_named_cell_style_init(self, name=None, *args, **kwargs):
    if name is None:
        name = "CostX_Recovered_Style"
    _original_named_cell_style_init(self, name=name, *args, **kwargs)

NamedCellStyle.__init__ = _patched_named_cell_style_init
# -----------------------------------

db_lock = threading.Lock()
progress_lock = threading.Lock()
completed_batches = 0

# Configuration
from core.config import FAISS_PATH, INBOX_PATH, DB_PATH

MODEL_NAME = "mmistral/mistral/mistral-embed"
TRACKER_FILE = "D:/Jarvis_QS/ingested_files.json"
BATCH_SIZE = 50
MAX_WORKERS = 4
CHECKPOINT_FILE = "D:/Jarvis_QS/batch_checkpoint.json"
STAGING_FILE = "D:/Jarvis_QS/staging_chunks.pkl"

SUPPORTED_EXTENSIONS = ('.pdf', '.docx', '.xlsx', '.xls', '.csv', '.tsv', '.txt', '.md', '.eml')


def load_checkpoint() -> set:
    """Load the set of already-completed batch indices from checkpoint file."""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                data = json.load(f)
                return set(data.get("completed_batches", []))
        except Exception:
            return set()
    return set()


def save_batch_checkpoint(batch_idx: int):
    """Atomically record a batch index as completed in the checkpoint file."""
    with progress_lock:
        completed = load_checkpoint()
        completed.add(batch_idx)
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump({"completed_batches": list(completed)}, f)


def get_safe_path(path: str) -> str:
    """Prepends the Windows long-path prefix to bypass the 260-character limit."""
    abs_path = os.path.abspath(path)
    if os.name == 'nt' and not abs_path.startswith('\\\\?\\'):
        return '\\\\?\\' + abs_path
    return abs_path


def load_tracker():
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_tracker(tracker_data):
    with open(TRACKER_FILE, "w") as f:
        json.dump(tracker_data, f, indent=4)


def extract_pdf(path: Path) -> str:
    text_accumulator = []
    try:
        doc = pymupdf.open(path)
        for idx, page in enumerate(doc):
            if idx >= 50:  # First 50 pages to save memory/tokens
                break
            txt = page.get_text()
            if txt:
                text_accumulator.append(f"--- Page {idx + 1} ---")
                text_accumulator.append(txt)
        doc.close()
    except Exception as e:  # noqa: BLE001
        print(f"Error PDF {path.name}: {e}")
    return "\n".join(text_accumulator)


def extract_docx(path: Path) -> str:
    text_accumulator = []
    try:
        doc = docx.Document(path)
        for para in doc.paragraphs:
            if para.text.strip():
                text_accumulator.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                row_str = " | ".join([cell.text.strip() for cell in row.cells if cell.text.strip()])
                if row_str:
                    text_accumulator.append(row_str)
    except Exception as e:  # noqa: BLE001
        print(f"Error DOCX {path.name}: {e}")
    return "\n".join(text_accumulator)


def parse_costx_excel_to_text(file_path: str) -> str:
    text_accumulator = []
    try:
        import pandas as pd
        # Use Rust-powered calamine engine to avoid openpyxl named style crashes
        xl = pd.ExcelFile(file_path, engine='calamine')
        for sheet_name in xl.sheet_names:
            df = xl.parse(sheet_name)
            text_accumulator.append(f"--- Sheet: {sheet_name} ---")
            for _, row in df.iterrows():
                row_vals = [str(val) for val in row.values if pd.notna(val) and str(val).strip() != ""]
                if row_vals:
                    text_accumulator.append(" | ".join(row_vals))
        return "\n".join(text_accumulator)
    except Exception as e:
        print(f"❌ Error parsing {file_path} with calamine: {repr(e)}")
        return ""


def extract_excel(path: Path) -> str:
    file_path = str(path)
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in (".csv", ".tsv"):
        try:
            sep = '\t' if ext == '.tsv' else ','
            df = pd.read_csv(file_path, sep=sep, encoding='utf-8', on_bad_lines='skip')
            df = df.dropna(how='all').dropna(axis=1, how='all')
            text_accumulator = []
            if ext == '.csv':
                text_accumulator.append(f"--- CSV: {path.stem} ---")
            else:
                text_accumulator.append(f"--- Table: {os.path.basename(file_path)} ---")
            for idx, row in df.iterrows():
                row_str = " | ".join([str(val) for val in row.values if pd.notna(val) and str(val).strip() != ""])
                if row_str:
                    text_accumulator.append(row_str)
            return "\n".join(text_accumulator)
        except Exception as e:
            print(f"Error Spreadsheet {ext[1:].upper()} {path.name}: {e}")
            return ""
    else:
        return parse_costx_excel_to_text(file_path)


def parse_any_document(file_path) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    text_accumulator = []

    try:
        # 1. Plain Text & Markdown (.txt, .md)
        if ext in ('.txt', '.md'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        # 2. Email Correspondence (.eml)
        elif ext == '.eml':
            with open(file_path, 'rb') as f:
                msg = email.message_from_binary_file(f, policy=policy.default)
                text_accumulator.append(f"Subject: {msg.get('subject', '')}")
                text_accumulator.append(f"From: {msg.get('from', '')}")
                text_accumulator.append(f"To: {msg.get('to', '')}")
                text_accumulator.append(f"Date: {msg.get('date', '')}")
                text_accumulator.append("--- Message Body ---")
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            text_accumulator.append(part.get_content())
                else:
                    text_accumulator.append(msg.get_content())
            return "\n".join(text_accumulator)

        # 3. Comma / Tab-Separated Values (.csv, .tsv)
        elif ext in ('.csv', '.tsv'):
            return extract_excel(Path(file_path))

        # 4. Excel & CostX Spreadsheets (.xlsx, .xls, .xlsX, .XLSX)
        elif ext in ('.xlsx', '.xls'):
            return extract_excel(Path(file_path))

        # 5. Word Documents (.docx)
        elif ext == '.docx':
            return extract_docx(Path(file_path))

        # 6. PDF Documents (.pdf)
        elif ext == '.pdf':
            return extract_pdf(Path(file_path))

    except Exception as e:
        print(f"Error parsing file {file_path}: {e}")
        return ""

    return ""


def process_single_batch(batch_idx, total_batches, batch_docs, vectorstore, embeddings, max_retries=6, is_sub_batch=False):
    global completed_batches
    start_time = time.time()

    # If the batch gets split down to a single chunk and STILL fails, we have a corrupt/massive chunk
    if not batch_docs:
        return True

    texts = [doc.page_content for doc in batch_docs]
    metadatas = [doc.metadata for doc in batch_docs]

    for attempt in range(1, max_retries + 1):
        try:
            # 1. NETWORK CALL
            embedded_vectors = embeddings.embed_documents(texts)
            text_embeddings = list(zip(texts, embedded_vectors))

            # 2. IN-MEMORY WRITE
            with db_lock:
                vectorstore.add_embeddings(text_embeddings, metadatas=metadatas)
                if not is_sub_batch and completed_batches % 100 == 0:
                    vectorstore.save_local(FAISS_PATH)

            elapsed = time.time() - start_time
            with progress_lock:
                if not is_sub_batch:
                    completed_batches += 1
                    print(f"✅ [{completed_batches}/{total_batches}] Batch {batch_idx} indexed ({len(batch_docs)} chunks) in {elapsed:.2f}s")
                else:
                    print(f"   ↳ ✅ Batch {batch_idx} partial segment ({len(batch_docs)} chunks) in {elapsed:.2f}s")
            return True

        except Exception as e:
            error_str = str(e).lower()

            # ERROR TYPE 1: TOKEN LIMIT -> Bisect Immediately
            if "too many tokens" in error_str:
                if len(batch_docs) > 1:
                    print(f"✂️ Batch {batch_idx} hit token limit. Bisecting {len(batch_docs)} chunks...")
                    mid = len(batch_docs) // 2
                    success1 = process_single_batch(batch_idx, total_batches, batch_docs[:mid], vectorstore, embeddings, max_retries=3, is_sub_batch=True)
                    success2 = process_single_batch(batch_idx, total_batches, batch_docs[mid:], vectorstore, embeddings, max_retries=3, is_sub_batch=True)

                    if not is_sub_batch and success1 and success2:
                        with progress_lock:
                            completed_batches += 1
                            print(f"✅ [{completed_batches}/{total_batches}] Batch {batch_idx} completely recovered via bisection!")
                    return success1 and success2
                else:
                    print(f"❌ FATAL: Chunk in Batch {batch_idx} failed token limit: {repr(e)}")
                    return False

            # ERROR TYPE 2: RATE LIMIT (429) -> Long Sleep
            elif "rate limit" in error_str or "429" in error_str:
                if attempt < max_retries:
                    wait_time = 15 * attempt  # Wait 15s, 30s, 45s, etc.
                    print(f"⏳ Rate limit hit on Batch {batch_idx}. Worker pausing for {wait_time}s to let API cool down...")
                    time.sleep(wait_time)
                else:
                    print(f"❌ Batch {batch_idx} failed after {max_retries} rate limit delays.")
                    return False

            # ERROR TYPE 3: STANDARD NETWORK DROP -> Short Sleep
            else:
                if attempt < max_retries:
                    wait_time = 2 * attempt
                    print(f"⚠️ Batch {batch_idx} attempt {attempt} failed: {repr(e)}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"❌ Batch {batch_idx} permanently failed: {repr(e)}")
                    return False


def run_incremental_sync() -> str:
    print(f"Starting Knowledge Vault Indexer (Incremental Mode) for: {INBOX_PATH}...")
    target_dir = Path(INBOX_PATH)

    if not target_dir.exists():
        target_dir.mkdir(parents=True)
        return "Inbox folder created. Please add your PDF/Excel files and run again."

    tracker = load_tracker()
    new_tracker_data = tracker.copy()
    files_to_process = []
    new_chunks = []

    # 1. ALWAYS perform dynamic directory scan to find all files needing sync
    scan_new_files = []
    print("📂 Scanning inbox for new or modified documents...")
    for root, _, files in os.walk(INBOX_PATH):
        for file in files:
            if not file.lower().endswith(SUPPORTED_EXTENSIONS):
                continue

            standard_path = os.path.join(root, file)
            safe_path = get_safe_path(standard_path)

            try:
                mtime = os.path.getmtime(safe_path)
                # If new or modified, register it
                if safe_path not in tracker or tracker[safe_path] < mtime:
                    scan_new_files.append((safe_path, mtime))
            except Exception as e:
                print(f"⚠️ Skipping unreadable file {file}: {e}")

    # 2. Check if staging cache exists
    if os.path.exists(STAGING_FILE):
        print("⚡ Found staging cache! Loading staging cache...")
        try:
            with open(STAGING_FILE, "rb") as f:
                staging_data = pickle.load(f)
                if isinstance(staging_data, tuple):
                    new_chunks, new_tracker_data, files_to_process = staging_data
                else:
                    new_chunks = staging_data
                    new_tracker_data = tracker.copy()
                    files_to_process = []
        except Exception as e:
            print(f"⚠️ Error reading staging cache: {e}. Re-indexing from scratch.")
            new_chunks = []
            new_tracker_data = tracker.copy()
            files_to_process = []

    # 3. Force Dynamic Directory Scan over Blind Staging Pickles:
    # Check if there are newly modified/added files in scan_new_files that are NOT in files_to_process
    newly_added_files = []
    for fp, mtime in scan_new_files:
        if fp not in files_to_process:
            newly_added_files.append(fp)
            files_to_process.append(fp)
            new_tracker_data[fp] = mtime

    # 4. If there are newly added files, parse, chunk, and append to new_chunks!
    if newly_added_files:
        print(f"🔄 Processing {len(newly_added_files)} newly added/modified file(s)...")
        documents = []
        metadatas = []
        for fp in newly_added_files:
            path = Path(fp)
            ext = os.path.splitext(fp)[1].lower()
            raw_path_str = fp[4:] if fp.startswith('\\\\?\\') else fp
            rel_path = Path(raw_path_str).relative_to(Path(INBOX_PATH).resolve())

            content = parse_any_document(fp)

            if content and content.strip():
                documents.append(content)
                metadatas.append({
                    "filename": path.name,
                    "category": str(rel_path.parent),
                    "file_type": ext,
                })
                print(f"Read and parsed: {path.name}")

        if documents:
            print("\nSanitizing document text (removing NaN, collapsing excess whitespace)...")
            cleaned_documents = []
            cleaned_metadatas = []
            for text, meta in zip(documents, metadatas):
                cleaned_text = re.sub(r'\bNaN\b|\bnan\b', '-', text)
                cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
                cleaned_text = cleaned_text.strip()
                if len(cleaned_text) > 10:
                    cleaned_documents.append(cleaned_text)
                    cleaned_metadatas.append(meta)

            if cleaned_documents:
                print("\nSplitting texts into optimized chunks...")
                splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200)
                split_chunks = splitter.create_documents(cleaned_documents, metadatas=cleaned_metadatas)
                new_chunks.extend(split_chunks)

        # Save the updated staging cache to disk
        print(f"💾 Saving {len(new_chunks)} total staging parsed chunks to staging area...")
        with open(STAGING_FILE, "wb") as f:
            pickle.dump((new_chunks, new_tracker_data, files_to_process), f)

    if not new_chunks:
        print("✅ No new files detected. Vault is up to date!")
        return "No new files detected. Vault is up to date!"

    if new_chunks:
        total_chunks = len(new_chunks)
        print(f"Found {total_chunks} new/modified chunks to process.")

        from langchain_community.embeddings import HuggingFaceEmbeddings

        print("Initializing Native HuggingFace embeddings (all-MiniLM-L6-v2)...")
        # model_kwargs={'device': 'cpu'} ensures it runs smoothly on standard hardware without GPU overhead crashes
        embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': False, 'batch_size': 100}
        )

        print("Initializing FAISS Vector Store...")
        # Safe FAISS Loading / Initialization Check
        index_file_path = os.path.join(FAISS_PATH, "index.faiss")
        pkl_file_path = os.path.join(FAISS_PATH, "index.pkl")

        if os.path.exists(index_file_path) and os.path.exists(pkl_file_path):
            print("Loading existing FAISS database...")
            vectorstore = FAISS.load_local(FAISS_PATH, embeddings, allow_dangerous_deserialization=True)
        else:
            print("No existing FAISS database found. Initializing a brand-new vector store...")
            vectorstore = None

        print("Generating Vector Embeddings via Native HuggingFace Embeddings (all-MiniLM-L6-v2)...")
        print(f"Appending {total_chunks} new chunks to FAISS...")

        batches = [new_chunks[i : i + BATCH_SIZE] for i in range(0, len(new_chunks), BATCH_SIZE)]
        total_batches = len(batches)

        completed_indices = load_checkpoint()
        pending_batches = [
            (idx + 1, batch)
            for idx, batch in enumerate(batches)
            if (idx + 1) not in completed_indices
        ]

        print(f"📊 Checkpoint loaded: {len(completed_indices)} batches already completed.")
        print(f"🚀 Processing remaining {len(pending_batches)} batches...")

        # Reset completed_batches for thread safety across multiple calls
        global completed_batches
        with progress_lock:
            completed_batches = len(completed_indices)

        failed_batches = 0
        if vectorstore is None:
            if pending_batches:
                first_batch_idx, first_batch_chunks = pending_batches[0]
                try:
                    print(f"Initializing FAISS vector store with first batch (Batch {first_batch_idx})...")
                    vectorstore = FAISS.from_texts(
                        texts=[chunk.page_content for chunk in first_batch_chunks],
                        embedding=embeddings,
                        metadatas=[chunk.metadata for chunk in first_batch_chunks]
                    )
                    # Successfully initialized; pop from pending_batches and update progress
                    pending_batches.pop(0)
                    with progress_lock:
                        completed_batches += 1
                    completed_indices.add(first_batch_idx)
                    save_batch_checkpoint(first_batch_idx)
                except Exception as e:
                    print(f"❌ Error initializing FAISS vector store: {e}")
                    failed_batches += 1

        if vectorstore is None:
            print("❌ Cannot proceed with batch ingestion: FAISS vector store is not initialized.")
            failed_batches += len(pending_batches)
        else:
            if pending_batches:
                print(f"🚀 Starting multi-threaded ingestion with {MAX_WORKERS} parallel workers across {len(pending_batches)} remaining batches...")
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {
                        executor.submit(process_single_batch, batch_idx, total_batches, batch, vectorstore, embeddings): batch_idx
                        for batch_idx, batch in pending_batches
                    }
                    for future in as_completed(futures):
                        if not future.result():
                            failed_batches += 1

        # Save final database if initialized
        if vectorstore is not None:
            print("💾 Saving final FAISS database to disk...")
            vectorstore.save_local(FAISS_PATH)

        if failed_batches == 0:
            save_tracker(new_tracker_data)
            if os.path.exists(STAGING_FILE):
                try:
                    os.remove(STAGING_FILE)
                except Exception:
                    pass
            if os.path.exists(CHECKPOINT_FILE):
                try:
                    os.remove(CHECKPOINT_FILE)
                except Exception:
                    pass
            print(f"\n🎉 SUCCESS: All {len(new_chunks)} chunks indexed into FAISS!")
            print("✅ Incremental sync complete!")
            return f"Successfully synced and indexed {len(files_to_process)} new/modified files."
        else:
            print(f"\n⚠️ Finished with {failed_batches} failed batches. Re-run to process remaining items.")
            return f"Finished with {failed_batches} failed batches. Re-run to process remaining items."
    else:
        return "No readable text found to index."


if __name__ == "__main__":
    # Allow manual terminal execution
    print(run_incremental_sync())