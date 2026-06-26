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
    if not api_keys: return
    client = genai.Client(api_key=api_keys[0])
    while not stop_flag:
        try:
            chunk_data = job_queue.get(timeout=1.0)
            chunk_idx, filename, lk_time = chunk_data
            
            # Gemini API එකට යැවීම
            audio_file = client.files.upload(file=filename)
            response = client.models.generate_content(
                model='gemini-1.5-flash',
                contents=[audio_file, "Transcribe the audio in Sinhala/Tamil/English scripts. Do not translate. Only output the transcription."]
            )
            
            final_transcripts[chunk_idx] = f"[{lk_time}] : {response.text}\n\n"
            client.files.delete(name=audio_file.name)
            os.remove(filename)
            job_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            # මොනවා හරි එරර් එකක් ආවොත් ඒකත් UI එකේ පෙන්නනවා
            final_transcripts[chunk_idx] = f"[{lk_time}] ERROR: {str(e)}\n\n"
            try: os.remove(filename)
            except: pass
            job_queue.task_done()

# Streamlit UI
st.title("🎙️ AI Live Transcriber")
url = st.text_input("Enter YouTube Live URL")

if st.button("Start Transcribing"):
    if not api_keys:
        st.error("⚠️ GEMINI_KEYS not found in Secrets!")
        st.stop()

    stop_flag = False
    final_transcripts.clear()
    
    st.info("🔗 Extracting Stream URL...")

    try:
        ydl_opts = {
            'format': 'bestaudio/best', 
            'quiet': True, 
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                st.error("⚠️ Could not extract video info.")
                st.stop()
            stream_url = info.get('url')
    except Exception as e:
        st.error(f"⚠️ Stream Extraction Error: {str(e)}")
        st.stop()
    
    # FFmpeg Process එකේ stderr=subprocess.PIPE කියලා වෙනස් කරා
    process = subprocess.Popen(
        ["ffmpeg", "-i", stream_url, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1"], 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE 
    )
    
    threading.Thread(target=worker_thread, daemon=True).start()
    
    debug_area = st.empty()
    output_area = st.empty()
    buffer = b""
    
    st.success("🎙️ System Live! Listening to audio...")

    while True:
        frame = process.stdout.read(32000)
        if not frame: 
            # FFmpeg එක නැවතුණාම, ඒකට හේතුව මොකක්ද කියලා අරන් පෙන්නනවා
            error_output = process.stderr.read().decode('utf-8')
            debug_area.error(f"⚠️ FFmpeg stopped. Reason:\n\n{error_output}")
            break
        
        buffer += frame
        
        # ලයිව් කවුන්ටරය (තත්පර 10ක් පිරෙනකම් පෙන්නයි)
        debug_area.info(f"⚙️ Recording audio chunk... {len(buffer) // 32000} / 10 seconds")
        
        # තත්පර 10ක් වුණාම API එකට යවනවා
        if len(buffer) >= 32000 * 10:
            filename = f"chunk_{time.time()}.wav"
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(buffer)
            
            lk_time = datetime.now(pytz.timezone("Asia/Colombo")).strftime("%H:%M:%S")
            job_queue.put((str(time.time()), filename, lk_time))
            buffer = b""
            
        # UI එක අප්ඩේට් කිරීම
        if final_transcripts:
            display_text = "".join([final_transcripts[k] for k in sorted(final_transcripts.keys())])
            output_area.text(display_text)
        else:
            output_area.text("🎙️ Transcribing... (Waiting for Gemini API to process the first chunk)")
