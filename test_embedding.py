from langchain_openai import OpenAIEmbeddings

MODEL_NAME = "mistral/mistral/mistral-embed"

print(f"Testing OmniRoute embedding model: {MODEL_NAME}...")

embeddings = OpenAIEmbeddings(
    model=MODEL_NAME,
    openai_api_base="https://omni.dhanrickeviota.com/v1",
    openai_api_key="sk-9e731d7385077d7e-2cbf0c-598b3170",
    check_embedding_ctx_length=False,
    max_retries=0,
)

try:
    sample_text = "Testing embedding model for Jarvis QS."
    result = embeddings.embed_query(sample_text)
    
    print("\n[SUCCESS] Embedding model works perfectly.")
    print(f"Vector Dimensions returned: {len(result)}")
    print(f"Sample values: {result[:5]}...")
    
except Exception as e:
    print("\n[ERROR] EMBEDDING TEST FAILED:")
    print(str(e))