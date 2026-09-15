import os
import logging
import threading
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import ffmpeg
import turso

# লগিং সেটআপ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# এনভায়রনমেন্ট ভেরিয়েবল থেকে কনফিগারেশন নিন
TOKEN = os.environ.get('BOT_TOKEN')
TURSO_URL = os.environ.get('TURSO_DB_URL')
TURSO_TOKEN = os.environ.get('TURSO_DB_AUTH_TOKEN')
CLIP_DURATION = 60  # ক্লিপের দৈর্ঘ্য সেকেন্ডে (এখানে ৬০ সেকেন্ড)

# ডেটাবেস ইনিশিয়ালাইজেশন ফাংশন
def init_db():
    """Turso ডেটাবেসে কানেক্ট করে টেবিল তৈরি করে"""
    try:
        conn = turso.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
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
        logger.info("ডেটাবেস সফলভাবে কানেক্ট হয়েছে।")
        return conn
    except Exception as e:
        logger.error(f"ডেটাবেস কানেকশন এরর: {e}")
        return None

# /start কমান্ড হ্যান্ডলার
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '🎬 হ্যালো! আমাকে একটি YouTube লিঙ্ক পাঠান, আমি সেটিকে ছোট ছোট ক্লিপে কেটে আপনাকে ফেরত দেব।'
    )

# YouTube ভিডিও ডাউনলোড ফাংশন
async def download_video(url: str) -> str:
    """yt-dlp ব্যবহার করে YouTube থেকে ভিডিও ডাউনলোড করে"""
    os.makedirs('downloads', exist_ok=True)
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
    return filename

# ভিডিও ক্লিপিং ফাংশন
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
            (
                ffmpeg
                .input(input_path, ss=start, t=clip_duration)
                .output(output, c='copy') # দ্রুত কপি করার জন্য c='copy'
                .overwrite_output()
                .run(quiet=True)
            )
            clips.append(output)
    except Exception as e:
        logger.error(f"ভিডিও স্প্লিট এরর: {e}")
    return clips

# মেসেজ হ্যান্ডলার (YouTube লিঙ্ক প্রসেস করার জন্য)
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    # চেক করুন এটি YouTube লিঙ্ক কিনা
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

        # ৩. ডেটাবেস কানেকশন নিন
        conn = context.bot_data.get('db_conn')
        if not conn:
            conn = init_db()
            context.bot_data['db_conn'] = conn

        # ৪. ক্লিপগুলো টেলিগ্রামে পাঠান
        for idx, clip_path in enumerate(clips, 1):
            with open(clip_path, 'rb') as video:
                await update.message.reply_video(
                    video=video,
                    caption=f'ক্লিপ {idx}/{len(clips)}'
                )
            
            # ডেটাবেসে সেভ করুন
            if conn:
                conn.execute(
                    "INSERT INTO clips (user_id, video_title, clip_number) VALUES (?, ?, ?)",
                    (update.effective_user.id, os.path.basename(video_path), idx)
                )
                conn.commit()
            
            # অস্থায়ী ক্লিপ ফাইলটি মুছে ফেলুন
            os.remove(clip_path)

        await update.message.reply_text('✅ সব ক্লিপ পাঠানো সম্পন্ন হয়েছে!')

    except Exception as e:
        logger.error(f"প্রসেসিং এরর: {e}")
        await update.message.reply_text(f'❌ দুঃখিত, একটি সমস্যা হয়েছে: {str(e)}')
    finally:
        # মূল ভিডিও ফাইলটি মুছে ফেলুন
        if video_path and os.path.exists(video_path):
            os.remove(video_path)

# Render-এর জন্য ওয়েব সার্ভার (UptimeRobot পিং করার জন্য)
def run_web_server():
    """Render-এর হেলথ চেক এবং UptimeRobot পিং এর জন্য একটি ডামি ওয়েব সার্ভার"""
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text="Bot is alive!"))
    
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"ওয়েব সার্ভার পোর্ট {port} এ চালু হচ্ছে...")
    web.run_app(app, host='0.0.0.0', port=port)

# মূল ফাংশন
def main():
    # Render-এর জন্য ওয়েব সার্ভারটি একটি আলাদা থ্রেডে চালান
    threading.Thread(target=run_web_server, daemon=True).start()

    # ডেটাবেস কানেকশন তৈরি করুন
    db_conn = init_db()
    
    # টেলিগ্রাম বট অ্যাপ্লিকেশন তৈরি করুন
    app = Application.builder().token(TOKEN).build()
    
    # ডেটাবেস কানেকশনটি bot_data তে সেভ করুন যাতে সব হ্যান্ডলার এটি ব্যবহার করতে পারে
    app.bot_data['db_conn'] = db_conn
    
    # হ্যান্ডলার যোগ করুন
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    
    logger.info("বট চালু হচ্ছে...")
    app.run_polling()

if __name__ == '__main__':
    main()
