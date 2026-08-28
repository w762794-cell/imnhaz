FROM python:3.11-slim

# ffmpeg ត្រូវការសម្រាប់ pydub (SRT->Audio) និង transcribe.py (ទាញ audio ពី video)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render កំណត់ PORT ដោយស្វ័យប្រវត្តិតាម environment variable ឈ្មោះ PORT
ENV PORT=10000
EXPOSE 10000

CMD ["python", "bot.py"]
