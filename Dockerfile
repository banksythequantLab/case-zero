# CASE ZERO — Mission Control on Cloud Run
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CASEZERO_BACKEND=firestore

WORKDIR /app

# deps first so the layer caches across code edits
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY casezero/ ./casezero/
COPY board.html ./
COPY corpus/ ./corpus/

# The serving container gets the CORPUS and nothing else. The complaint and the
# derived ground_truth.json stay out entirely — scoring is a separate step run
# after the fleet stops. If the answer key is not in the image, "did the agents
# peek?" is not a question anyone has to take on trust.
RUN test ! -e complaint.pdf && test ! -e complaint.txt && test ! -e ground_truth.json

# Cloud Run sets $PORT. Bind 0.0.0.0 or the container is unreachable.
ENV PORT=8080
EXPOSE 8080
CMD ["python", "-m", "casezero.board"]
