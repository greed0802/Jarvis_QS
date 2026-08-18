import requests

try:
    response = requests.get("https://omni.dhanrickeviota.com/v1/models").json()
    print("Available Embedding Models in OmniRoute:\n")
    for model in response.get("data", []):
        model_id = model.get("id", "")
        # Filter for models with 'embed' in the name
        if "embed" in model_id.lower():
            print(f" - {model_id}")
except Exception as e:
    print(f"Error fetching models: {e}")