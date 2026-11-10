"""`python -m vendorcheck` starts the app on http://localhost:8000"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("vendorcheck.web.app:get_app", factory=True, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), log_level="info")
