import os
import json
import sys
import requests

# Simple script to send NGSI-LD batch forecast
# Usage: python request.py [payload_file]

# Determine payload file path (default: payload.json)
payload_file = sys.argv[1] if len(sys.argv) > 1 else "payload.json"

# Determine endpoint URL (default via environment or fallback)
url = os.getenv("NGSI_URL", "http://localhost:9013/ngsi-ld/batch_forecast")

# Load API key from environment variable
api_key = "mykey2023"
if not api_key:
    print("Error: please set NGSI_API_KEY environment variable.")
    sys.exit(1)

# Read JSON payload
try:
    with open(payload_file, 'r', encoding='utf-8') as f:
        payload = json.load(f)
except Exception as e:
    print(f"Failed to read payload file '{payload_file}': {e}")
    sys.exit(1)

# Send POST request

# Send POST request
try:
    response = requests.post(
        url,
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-KEY": api_key
        }
    )
    response.raise_for_status()
except requests.RequestException as e:
    print(f"Request failed: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print("Response:", e.response.text)
    sys.exit(1)

# Print status and save the body to a file
print(f"Status code: {response.status_code}")

# Choose a filename (you can also parameterize this)
output_file = "response.json"

# Try to parse JSON, otherwise dump as text
try:
    data = response.json()
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Response JSON written to {output_file}")
except ValueError:
    # Not valid JSON—write raw text
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(response.text)
    print(f"Response text written to {output_file}")