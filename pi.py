import os
import time
import random
import requests
from datetime import datetime

IMAGES_DIR = "pi_images"

# 🔴 IMPORTANT: replace this with your PC's IPv4 from ipconfig
SERVER_URL = "http://192.168.50.136:8000/api/image"

INTERVAL_SECONDS = 600  # 10 minutes


def get_image_files():
    files = [
        f for f in os.listdir(IMAGES_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    if not files:
        raise RuntimeError(f"No image files found in {IMAGES_DIR}")
    return files


def main():
    files = get_image_files()
    print(f"Found {len(files)} images. Starting upload loop...")

    while True:
        filename = random.choice(files)
        path = os.path.join(IMAGES_DIR, filename)

        with open(path, "rb") as img:
            files_dict = {"file": (filename, img, "image/jpeg")}
            try:
                resp = requests.post(SERVER_URL, files=files_dict)
                print(
                    datetime.now().isoformat(timespec="seconds"),
                    "->", resp.status_code,
                    resp.text[:200]
                )
            except Exception as e:
                print("Error sending image:", e)

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
