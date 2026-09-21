FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg git && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# yt-dlp আপডেট এবং PO Token প্লাগইন ইনস্টল
RUN pip install --no-cache-dir --upgrade -r requirements.txt && \
    pip install --no-cache-dir -U yt-dlp bgutil-ytdlp-pot-provider

COPY . .

CMD ["python", "bot.py"]
