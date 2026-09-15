import os
import logging
import threading
import asyncio
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import ffmpeg
import turso_serverless

# ---------- লগিং সেটআপ ----------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- এনভায়রনমেন্ট ভেরিয়েবল ----------
TOKEN = os.environ.get('BOT_TOKEN')
TURSO_URL = os.environ.get('TURSO_DB_URL')
TURSO_TOKEN = os.environ.get('TURSO_DB_AUTH_TOKEN')
CLIP_DURATION = 60  # ক্লিপের দৈর্ঘ্য সেকেন্ডে (৬০ সেকেন্ড)

# ---------- ডেটাবেস ইনিশিয়ালাইজেশন ----------
def init_db():
    """Turso ক্লাউড ডেটাবেসে কানেক্ট করে টেবিল তৈরি করে"""
    try:
        conn = turso_serverless.connect(
            TURSO_URL,
            auth_token=TURSO_TOKEN
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                video_title TEXT,
                clip_number INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logger.info("✅ ডেটাবেস সফলভাবে কানেক্ট হয়েছে।")
        return conn
    except Exception as e:
        logger.error(f"❌ ডেটাবেস কানেকশন এরর: {e}")
        return None

# ---------- /start কমান্ড ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '🎬 হ্যালো! আমাকে একটি YouTube লিঙ্ক পাঠান, '
        'আমি সেটিকে ছোট ছোট ক্লিপে কেটে আপনাকে ফেরত দেব।'
    )

# ---------- YouTube ভিডিও ডাউনলোড (কুকিজ সহ) ----------
async def download_video(url: str) -> str:
    """yt-dlp ব্যবহার করে YouTube থেকে ভিডিও ডাউনলোড করে (cookies.txt সহ)"""
    os.makedirs('downloads', exist_ok=True)
    
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        # GitHub-এ আপলোড করা cookies.txt ফাইলটি ব্যবহার করবে
        'cookiefile': 'cookies.txt'
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    return filename

# ---------- ভিডিও ক্লিপিং ----------
async def split_video(input_path: str, clip_duration: int) -> list:
    """FFmpeg ব্যবহার করে ভিডিওকে ছোট ছোট ক্লিপে ভাগ করে"""
    clips = []
    os.makedirs('clips', exist_ok=True)
    try:
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])
        num_clips = int(duration // clip_duration) + 1

        for i in range(num_clips):
            start = i * clip_duration
            output = f"clips/clip_{i+1}.mp4"
            try:
                (
                    ffmpeg
                    .input(input_path, ss=start, t=clip_duration)
                    .output(output, c='copy')
                    .overwrite_output()
                    .run(quiet=True)
                )
                clips.append(output)
            except ffmpeg.Error as e:
                logger.error(f"ক্লিপ {i+1} তৈরিতে সমস্যা: {e}")
    except Exception as e:
        logger.error(f"ভিডিও স্প্লিট এরর: {e}")
    return clips

# ---------- মেসেজ হ্যান্ডলার ----------
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if 'youtube.com' not in url and 'youtu.be' not in url:
        await update.message.reply_text('❌ দয়া করে শুধু একটি বৈধ YouTube লিঙ্ক পাঠান।')
        return

    await update.message.reply_text('⏳ ভিডিও ডাউনলোড হচ্ছে... অপেক্ষা করুন।')
    video_path = None

    try:
        # ১. ভিডিও ডাউনলোড
        video_path = await download_video(url)
        await update.message.reply_text('✂️ ক্লিপ তৈরি হচ্ছে... এটি কিছুটা সময় নিতে পারে।')

        # ২. ভিডিও ক্লিপিং
        clips = await split_video(video_path, CLIP_DURATION)

        if not clips:
            await update.message.reply_text('❌ দুঃখিত, ক্লিপ তৈরি করা সম্ভব হয়নি।')
            return

        # ৩. ডেটাবেস কানেকশন
        conn = context.bot_data.get('db_conn')
        if not conn:
            conn = init_db()
            context.bot_data['db_conn'] = conn

        # ৪. ক্লিপগুলো টেলিগ্রামে পাঠান
        total = len(clips)
        for idx, clip_path in enumerate(clips, 1):
            try:
                with open(clip_path, 'rb') as video:
                    await update.message.reply_video(
                        video=video,
                        caption=f'ক্লিপ {idx}/{total}'
                    )

                if conn:
                    try:
                        conn.execute(
                            "INSERT INTO clips (user_id, video_title, clip_number) "
                            "VALUES (?, ?, ?)",
                            (update.effective_user.id,
                             os.path.basename(video_path), idx)
                        )
                        conn.commit()
                    except Exception as db_err:
                        logger.error(f"DB insert error: {db_err}")

                os.remove(clip_path)
            except Exception as send_err:
                logger.error(f"ক্লিপ পাঠাতে সমস্যা: {send_err}")

        await update.message.reply_text('✅ সব ক্লিপ পাঠানো সম্পন্ন হয়েছে!')

    except Exception as e:
        logger.error(f"প্রসেসিং এরর: {e}")
        await update.message.reply_text(f'❌ দুঃখিত, একটি সমস্যা হয়েছে: {str(e)}')
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass

# ---------- বট চালানোর ফাংশন (আলাদা থ্রেডে চলবে) ----------
async def run_bot():
    """টেলিগ্রাম বট চালু করে"""
    db_conn = init_db()
    app = Application.builder().token(TOKEN).build()
    app.bot_data['db_conn'] = db_conn
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("🤖 বট চালু হচ্ছে...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # বট চলতে থাকবে যতক্ষণ না প্রোগ্রাম বন্ধ হয়
    await asyncio.Event().wait()

def start_bot_thread():
    """আলাদা থ্রেডে বট চালু করে"""
    asyncio.run(run_bot())

# ---------- ওয়েব সার্ভার (মূল থ্রেডে চলবে) ----------
async def health_check(request):
    return web.Response(text="Bot is alive!")

def main():
    # টেলিগ্রাম বটকে আলাদা থ্রেডে চালান
    bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
    bot_thread.start()

    # ওয়েব সার্ভার মূল থ্রেডে চালান (Render-এর হেলথ চেকের জন্য)
    app = web.Application()
    app.router.add_get('/', health_check)
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"🌐 ওয়েব সার্ভার পোর্ট {port} এ চালু হচ্ছে...")
    web.run_app(app, host='0.0.0.0', port=port)

if __name__ == '__main__':
    main()
