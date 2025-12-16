# step_google.py — replaces the old file
import os
from dotenv import load_dotenv
from google import genai
from google.genai.errors import ClientError
import sys

load_dotenv()

key = os.environ.get("GEMINI_API_KEY")
print("API key loaded:", bool(key))

if not key:
    print("ERROR: GEMINI_API_KEY missing. Use export or .env file.")
    sys.exit(1)

client = genai.Client(api_key=key)

# First: collect models that support generateContent
supported = []
print("\nFetching available models (this may take 5–10s)...")
try:
    for m in client.models.list():
        # Some model descriptors store capabilities in supported_actions
        actions = getattr(m, "supported_actions", None) or getattr(m, "capabilities", None) or []
        if "generateContent" in actions:
            supported.append((m.name, getattr(m, "description", "")))
except ClientError as e:
    print("\nAPI error while listing models:", e)
    sys.exit(1)
except Exception as e:
    print("\nUnexpected error while listing models:", e)
    sys.exit(1)

if not supported:
    print("\nNo models that support generateContent were found for this API key.")
    print("Possible causes:")
    print(" - The API key lacks AI/GenAI permissions or hasn't been provisioned.")
    print(" - Billing or quota issues on the Google side.")
    print(" - The key is for a different Google API (not the AI Studio key).")
    print("\nTry these checks:")
    print(" 1) Verify your key in Google AI Studio (https://aistudio.google.com).")
    print(" 2) Ensure the key has access to models and the correct API version.")
    print(" 3) If you have a Google Cloud key instead, see docs on using Vertex/Cloud auth.")
    sys.exit(1)

# Print a short list for your visibility
print("\nFound the following models that support generateContent:")
for i, (name, desc) in enumerate(supported[:10], start=1):
    short = (desc[:120] + "...") if desc else ""
    print(f"{i}. {name}  {short}")

# Use the first supported model automatically
chosen_model = supported[0][0]
print("\nUsing model:", chosen_model)

# Make a test call
prompt = "Write one short paragraph (2-3 sentences) introducing Reconstruct — a mental fitness app."
try:
    response = client.models.generate_content(
        model=chosen_model,
        contents=prompt
    )
    # SDK response could expose .text or other attributes
    out = getattr(response, "text", None) or getattr(response, "response", None) or response
    print("\n== AI response ==\n")
    print(out)
except ClientError as e:
    print("\nAPI returned an error when calling the model:")
    print(e)
    # Print the server JSON if available
    try:
        print("Server response:", e.response_json)
    except Exception:
        pass
    sys.exit(1)
except Exception as e:
    print("\nUnexpected error calling the model:", e)
    sys.exit(1)
