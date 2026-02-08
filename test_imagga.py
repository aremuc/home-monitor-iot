import requests

API_KEY = "acc_23ecc162ef41c9c"
API_SECRET = "931c7d903328ff190eac5b8af90b8f60"

IMAGE_PATH = "golden_retriever.jpg"

with open(IMAGE_PATH, "rb") as img:
    response = requests.post(
        "https://api.imagga.com/v2/tags",
        auth=(API_KEY, API_SECRET),
        files={"image": img}
    )

print("Status code:", response.status_code)
print(response.json())