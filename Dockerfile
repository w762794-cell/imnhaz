FROM python:3.11-slim

# ffmpeg ត្រូវការសម្រាប់ pydub (SRT->Audio) និង transcribe.py (ទាញ audio ពី video)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# --- Download Whisper model ដាក់ចូល image ជាមុន (build time) ---
# សំខាន់ណាស់៖ បើមិនធ្វើបែបនេះទេ bot នឹងព្យាយាម download model ពេលវាដំណើរការ
# ជាលើកដំបូង (runtime) ដែលអាចគាំងគ្មានទីបញ្ចប់ បើ network មិនស្ថិតស្ថេរ
# (នេះជាមូលហេតុដែល transcribe ធ្លាប់ជាប់គាំងស្ថិតនៅ "download/load model")
# ARG អនុញ្ញាតឲ្យប្តូរ model size ពេល build បាន (ត្រូវតែដូចគ្នានឹង WHISPER_MODEL_SIZE
# environment variable ដែលកំណត់ក្នុង Render Dashboard)
ARG WHISPER_MODEL_SIZE=base
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL_SIZE}', device='cpu', compute_type='int8')"

# Render កំណត់ PORT ដោយស្វ័យប្រវត្តិតាម environment variable ឈ្មោះ PORT
ENV PORT=10000
EXPOSE 10000

CMD ["python", "bot.py"]
