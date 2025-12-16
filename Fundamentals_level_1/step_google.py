import os
from dotenv import load_dotenv
from google import genai

# Load .env file
load_dotenv()

# Print to confirm the key is loaded
print("API key loaded:", bool(os.environ.get("GEMINI_API_KEY")))

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-1.5-flash",
    contents="Hello Gemini! Say hi back."
)

print("\nGemini response:\n")
print(response.text)
