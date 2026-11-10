FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HOST=0.0.0.0 PORT=8000 VENDORCHECK_PACING_MS=700

# libraries the OCR stack (OpenCV) needs at runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# the browser-test and PDF-building tools are for development only
RUN grep -viE '^(playwright|pytest|reportlab)' requirements.txt > requirements.run.txt && pip install -r requirements.run.txt

COPY . .
# RBI bank directory, so IFSC checks work offline
RUN python -m vendorcheck.adapters.ifsc --download || echo "IFSC download skipped; run it again once online"

EXPOSE 8000
CMD ["python", "-m", "vendorcheck"]
