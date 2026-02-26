"""Show full test result details"""
import json

with open("test_result.json") as f:
    d = json.load(f)

# Print as formatted json, first 5000 chars
print(json.dumps(d, indent=2, default=str)[:5000])
