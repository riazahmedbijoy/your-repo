import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import ffmpeg
from pyturso import connect

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.environ.get('BOT_TOKEN')
TURSO_URL = os.environ.get('TURSO_DB_URL')
TURSO_TOKEN = os.environ.get('TURSO_DB_AUTH_TOKEN')
CLIP_DURATION = 60  # সেকেন্ডে

async def init_db():
    conn = await connect(TURSO_URL, auth_token=TURSO_TOKEN)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            video_title TEXT,
            clip_number INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return conn

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '🎬 হ্যালো! আমাকে একটি YouTube লিঙ্ক পাঠান, আমি সেটিকে ছোট ছোট ক্লিপে কেটে আপনাকে ফেরত দেব।'
    )

async def download_video(url: str) -> str:
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    return filename

async def split_video(input_path: str, clip_duration: int) -> list:
    clips = []
    try:
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])
        num_clips = int(duration // clip_duration) + 1

        for i in range(num_clips):
            start = i * clip_duration
            output = f"clips/clip_{i+1}.mp4"
            (
                ffmpeg
                .input(input_path, ss=start, t=clip_duration)
                .output(output, c='copy')
                .overwrite_output()
                .run(quiet=True)
            )
            clips.append(output)
    except Exception as e:
        logging.error(f"Split error: {e}")
    return clips

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if 'youtube.com' not in url and 'youtu.be' not in url:
        await update.message.reply_text('❌ শুধু YouTube লিঙ্ক পাঠান।')
        return

    await update.message.reply_text('⏳ ভিডিও ডাউনলোড হচ্ছে...')

    try:
        video_path = await download_video(url)
        await update.message.reply_text('✂️ ক্লিপ তৈরি হচ্ছে...')

        clips = await split_video(video_path, CLIP_DURATION)
        conn = await init_db()

        for idx, clip_path in enumerate(clips, 1):
            with open(clip_path, 'rb') as video:
                await update.message.reply_video(
                    video=video,
                    caption=f'ক্লিপ {idx}/{len(clips)}'
                )
            await conn.execute(
                "INSERT INTO clips (user_id, video_title, clip_number) VALUES (?, ?, ?)",
                (update.effective_user.id, os.path.basename(video_path), idx)
            )
            os.remove(clip_path)

        os.remove(video_path)
        await update.message.reply_text('✅ সব ক্লিপ পাঠানো সম্পন্ন!')
    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text('❌ দুঃখিত, সমস্যা হয়েছে। আবার চেষ্টা করুন।')

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.run_polling()

if __name__ == '__main__':
    main()
