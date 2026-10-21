"""
One-command launcher for the Recyclable Pricing Assistant.
Run from the project root with: python run.py
"""
from pathlib import Path
import importlib.util
import os
import secrets
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

def ensure_env():
    env_file = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_file.exists():
        content = example.read_text(encoding="utf-8") if example.exists() else ""
        secret = secrets.token_urlsafe(48)
        if re_search := __import__("re").search(r"(?m)^APP_SECRET=.*$", content):
            content = content[:re_search.start()] + f"APP_SECRET={secret}" + content[re_search.end():]
        else:
            content += f"\nAPP_SECRET={secret}\n"
        env_file.write_text(content, encoding="utf-8")
        print("Created .env with a new APP_SECRET.")
    # Load values before importing the application.
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        pass

def main():
    required = ["uvicorn", "fastapi", "pandas", "sklearn", "joblib", "dotenv", "cryptography"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        print("Some dependencies are missing:", ", ".join(missing))
        print("Install them from the project root with:")
        print(f'  "{sys.executable}" -m pip install -r requirements.txt')
        raise SystemExit(1)

    ensure_env()

    url = "http://127.0.0.1:8000/"
    print("\nStarting Recyclable Pricing Assistant...")
    print(f"Web app: {url}")
    print(f"API docs: {url}docs")
    print("Keep this terminal open while using the app. Press Ctrl+C to stop.\n")

    def open_browser():
        time.sleep(2)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()
    import uvicorn
    uvicorn.run("backend.api:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
