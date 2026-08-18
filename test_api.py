from langchain_openai import ChatOpenAI

print("Connecting to Omniroute Chat...")

# Use ChatOpenAI instead of OpenAIEmbeddings
llm = ChatOpenAI(
    model="antigravity/gemini-2.5-flash-thinking",
    openai_api_base="https://omni.dhanrickeviota.com/v1",
    openai_api_key="sk-9e731d7385077d7e-2cbf0c-598b3170",
    max_retries=0,       
    timeout=10,          
)

try:
    # Test with a standard chat invocation
    result = llm.invoke("Hello, Jarvis.")
    print(f"\n[SUCCESS] Reached API.")
    print(f"Response: {result.content}")
except Exception as e:
    print(f"\n[ERROR] FAILED TO REACH API:")
    print(str(e))
