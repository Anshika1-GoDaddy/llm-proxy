"""
Entry point for running the LLM proxy (used by PyInstaller binary and by direct run).
Reads HOST/PORT from env; default 0.0.0.0:8000.
"""
import os
import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host=host, port=port)
