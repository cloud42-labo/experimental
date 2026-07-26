import os


def load_app_id():
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("ESTAT_APP_ID="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("ESTAT_APP_ID not found in .env")
