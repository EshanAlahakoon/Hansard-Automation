import os
import subprocess
import threading
import queue
import wave
import time
import streamlit as st
import yt_dlp
from google import genai
from datetime import datetime
import pytz

# API setup
api_keys = [k.strip() for k in os.environ.get("GEMINI_KEYS", "").split(",") if k.strip()]
job_queue = queue.Queue()
final_transcripts = {}
stop_flag = False

def worker_thread():
    client = genai.Client(api_key=api_keys[0])
    while not stop_flag:
        try:
            chunk_data = job_queue.get(timeout=1.0)
            chunk_idx, filename, lk_time = chunk_data
            audio_file = client.files.upload(file=filename)
            response = client.models.generate_content(
                model='gemini-1.5-flash',
                contents=[audio_file, "Transcribe the audio in Sinhala/Tamil/English scripts."]
            )
            final_transcripts[chunk_idx] = f"[{lk_time}] : {response.text}\n\n"
            client.files.delete(name=audio_file.name)
            os.remove(filename)
            job_queue.task_done()
        except: continue

# Streamlit UI
st.title("🎙️ AI Live Transcriber")
url = st.text_input("Enter YouTube Live URL")

if st.button("Start Transcribing"):
    stop_flag = False
    final_transcripts = {}
    
    # URL extraction
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        stream_url = ydl.extract_info(url, download=False)['url']
    
    # FFmpeg Process
    process = subprocess.Popen(["ffmpeg", "-i", stream_url, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    # Start workers
    threading.Thread(target=worker_thread, daemon=True).start()
    
    output_area = st.empty()
    buffer = b""
    while True:
        frame = process.stdout.read(16000)
        if not frame: break
        buffer += frame
        if len(buffer) >= 32000 * 30:
            filename = f"chunk_{time.time()}.wav"
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(buffer)
            job_queue.put((str(time.time()), filename, datetime.now(pytz.timezone("Asia/Colombo")).strftime("%H:%M")))
            buffer = b""
            
        display_text = "".join(final_transcripts.values())
        st.write(f"DEBUG: Data length in buffer: {len(buffer)}")
        output_area.text(display_text or "🎙️ Transcribing...")
