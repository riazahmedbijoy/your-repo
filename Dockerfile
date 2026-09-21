FROM python:3.11-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .

# -U ফ্ল্যাগ yt-dlp কে লেটেস্ট ভার্সনে আপডেট করবে
RUN pip install --no-cache-dir -U -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
