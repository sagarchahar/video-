"""
╔══════════════════════════════════════════════════════════════╗
║          FACELESS VIDEO GENERATOR  —  main.py               ║
║  Stack: Streamlit · Pollinations.ai · edge-tts · MoviePy    ║
╚══════════════════════════════════════════════════════════════╝

Install dependencies before running:
    pip install streamlit requests edge-tts moviepy pillow

Run:
    streamlit run main.py
"""

# ── Monkey-patch: keep legacy Pillow code from crashing ──────────────────────
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

# ── Standard library ─────────────────────────────────────────────────────────
import asyncio
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

# ── Third-party ───────────────────────────────────────────────────────────────
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────────────────────
#  PAGE CONFIG  (must be the very first Streamlit call)
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Faceless Video Generator",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
#  GLOBAL CUSTOM CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Serif+Display&display=swap');

    html, body, [class*="css"] {
        font-family: 'Space Mono', monospace;
        background-color: #0d0d0f;
        color: #e8e3d9;
    }

    /* ── header bar ── */
    .app-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        border: 1px solid #e94560;
        border-radius: 12px;
        padding: 28px 36px;
        margin-bottom: 28px;
        position: relative;
        overflow: hidden;
    }
    .app-header::before {
        content: "◈";
        position: absolute;
        right: 24px; top: 50%; transform: translateY(-50%);
        font-size: 72px; color: rgba(233,69,96,0.15);
    }
    .app-header h1 {
        font-family: 'DM Serif Display', serif;
        font-size: 2.4rem;
        margin: 0; padding: 0;
        background: linear-gradient(90deg, #e94560, #f5a623);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .app-header p { margin: 6px 0 0; color: #8a8fa8; font-size: 0.82rem; }

    /* ── scene card ── */
    .scene-card {
        background: #12121a;
        border: 1px solid #2a2a3e;
        border-radius: 10px;
        padding: 14px;
        margin-bottom: 12px;
        transition: border-color 0.2s;
    }
    .scene-card:hover { border-color: #e94560; }
    .scene-label {
        font-size: 0.68rem; letter-spacing: 0.15em;
        color: #e94560; text-transform: uppercase; margin-bottom: 6px;
    }
    .scene-narration { font-size: 0.85rem; color: #c0bdb6; line-height: 1.55; }

    /* ── status badge ── */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 700;
        letter-spacing: 0.08em;
    }
    .badge-ok  { background:#1a3a2a; color:#4dff91; border:1px solid #4dff91; }
    .badge-err { background:#3a1a1a; color:#ff4d4d; border:1px solid #ff4d4d; }
    .badge-pending { background:#2a2a1a; color:#ffd04d; border:1px solid #ffd04d; }

    /* ── sidebar tweaks ── */
    section[data-testid="stSidebar"] {
        background: #0d0d14;
        border-right: 1px solid #1e1e2e;
    }
    section[data-testid="stSidebar"] .stTextInput input,
    section[data-testid="stSidebar"] .stSelectbox div[data-baseweb],
    section[data-testid="stSidebar"] .stSlider {
        background: #12121f !important;
        color: #e8e3d9 !important;
        border-color: #2a2a3e !important;
    }

    /* ── buttons ── */
    .stButton > button {
        background: linear-gradient(135deg, #e94560, #c0392b);
        color: #fff;
        border: none;
        border-radius: 8px;
        font-family: 'Space Mono', monospace;
        font-weight: 700;
        letter-spacing: 0.05em;
        padding: 0.55rem 1.4rem;
        transition: opacity 0.2s, transform 0.1s;
    }
    .stButton > button:hover { opacity: 0.88; transform: translateY(-1px); }
    .stButton > button:active { transform: translateY(0); }

    /* ── progress bar ── */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #e94560, #f5a623);
    }

    /* ── video player ── */
    video { border-radius: 12px; border: 2px solid #e94560; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
POLLINATIONS_TEXT_URL = "https://text.pollinations.ai/"
POLLINATIONS_IMAGE_URL = "https://image.pollinations.ai/prompt/"
IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720
IMAGE_INTER_REQUEST_DELAY = 5   # seconds between image API calls
IMAGE_MAX_RETRIES = 4
AUDIO_VOICE = "en-US-GuyNeural"  # edge-tts voice

# ─────────────────────────────────────────────────────────────────────────────
#  HELPER: run async from sync context
# ─────────────────────────────────────────────────────────────────────────────
def _run_async(coro):
    """Run an async coroutine from a synchronous context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)

# ─────────────────────────────────────────────────────────────────────────────
#  1. WRITER — Script generation via Pollinations Text API
# ─────────────────────────────────────────────────────────────────────────────
def generate_script(
    topic: str,
    art_style: str,
    max_scenes: int,
    char_name: str,
    char_desc: str,
) -> list[dict]:
    """
    Call the Pollinations text API and return a list of scene dicts:
      { "scene_number": int, "narration_text": str, "visual_prompt": str }
    """
    char_instruction = ""
    if char_name and char_desc:
        char_instruction = (
            f'\nIf the story includes a character named "{char_name}", '
            f'their visual description is: "{char_desc}". '
            "Make sure to reference this character naturally in the script."
        )

    system_prompt = (
        "You are a professional video scriptwriter specialising in faceless YouTube content. "
        "You output ONLY valid raw JSON — no markdown fences, no commentary."
    )

    user_prompt = f"""Write a {max_scenes}-scene script for a faceless video about: "{topic}".
{char_instruction}

Return a JSON array where each element has EXACTLY these keys:
  "scene_number"   : integer starting at 1
  "narration_text" : the voiceover text for this scene (2-4 sentences, engaging and informative)
  "visual_prompt"  : a detailed image generation prompt in the style of "{art_style}".
               Must be a single vivid paragraph describing the scene visuals.
               Do NOT include people's faces unless they are stylised/cartoon/silhouette.

Output only the JSON array. No other text."""

    payload = {
        "model": "llama",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.8,
    }

    try:
        resp = requests.post(POLLINATIONS_TEXT_URL, json=payload, timeout=90)
        resp.raise_for_status()
        raw = resp.text.strip()

        # Strip possible markdown fences
        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.MULTILINE).strip()
        raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()

        scenes = json.loads(raw)
        if not isinstance(scenes, list):
            raise ValueError("Expected a JSON array")
        return scenes[:max_scenes]

    except Exception as exc:
        st.error(f"Script generation failed: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
#  2. ARTIST — Image generation via Pollinations Image API
# ─────────────────────────────────────────────────────────────────────────────
def generate_image(
    prompt: str,
    scene_number: int,
    char_name: str,
    char_desc: str,
    art_style: str,
) -> Optional[bytes]:
    """
    Synchronous image generation with rate-limit retry and character injection.
    Returns raw PNG bytes or None on total failure.
    """
    # Inject character description if character is mentioned
    enhanced_prompt = prompt
    if char_name and char_desc and char_name.lower() in prompt.lower():
        enhanced_prompt = f"{prompt} Character appearance: {char_desc}."

    # Append art style suffix if not already present
    if art_style.lower() not in enhanced_prompt.lower():
        enhanced_prompt = f"{enhanced_prompt}, {art_style} style"

    # Safety/quality suffixes
    enhanced_prompt += (
        ", high quality, detailed, cinematic lighting, 16:9 aspect ratio, "
        "no watermark, no text overlay"
    )

    encoded = requests.utils.quote(enhanced_prompt)
    url = (
        f"{POLLINATIONS_IMAGE_URL}{encoded}"
        f"?width={IMAGE_WIDTH}&height={IMAGE_HEIGHT}"
        f"&model=flux&seed={scene_number * 42}&nologo=true"
    )

    for attempt in range(1, IMAGE_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=120)
            if resp.status_code == 429:
                wait = 15 * attempt
                st.toast(f"⏳ Scene {scene_number}: rate-limited, waiting {wait}s…")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.RequestException as exc:
            if attempt < IMAGE_MAX_RETRIES:
                time.sleep(IMAGE_INTER_REQUEST_DELAY * attempt)
            else:
                st.warning(f"Scene {scene_number} image failed after {IMAGE_MAX_RETRIES} attempts: {exc}")
                return None

    return None


def make_placeholder_frame() -> bytes:
    """Return a solid black 1280×720 PNG as a fallback frame."""
    img = PIL.Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), color=(10, 10, 15))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
#  3. SPEAKER — TTS via edge-tts
# ─────────────────────────────────────────────────────────────────────────────
async def _synthesise(text: str, output_path: str, voice: str) -> bool:
    """Async edge-tts synthesis."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(output_path)
        return True
    except Exception as exc:
        st.warning(f"TTS synthesis failed: {exc}")
        return False


def generate_audio(text: str, output_path: str, voice: str = AUDIO_VOICE) -> bool:
    """Synchronous wrapper around edge-tts synthesis."""
    return _run_async(_synthesise(text, output_path, voice))


def get_audio_duration(audio_path: str) -> float:
    """Return audio duration in seconds using moviepy."""
    try:
        from moviepy.editor import AudioFileClip
        with AudioFileClip(audio_path) as clip:
            return clip.duration
    except Exception:
        return 5.0  # fallback duration


# ─────────────────────────────────────────────────────────────────────────────
#  4. EDITOR — Video assembly via MoviePy
# ─────────────────────────────────────────────────────────────────────────────
def assemble_video(
    scene_data: list[dict],
    output_path: str,
) -> bool:
    """
    Assemble ImageClips + AudioClips into a final MP4.
    scene_data items: { image_bytes, audio_path, duration }
    """
    try:
        from moviepy.editor import (
            AudioFileClip,
            CompositeAudioClip,
            ImageClip,
            concatenate_videoclips,
        )
    except ImportError as e:
        st.error(f"MoviePy import error: {e}")
        return False

    clips = []
    for i, sd in enumerate(scene_data):
        img_bytes = sd.get("image_bytes") or make_placeholder_frame()
        audio_path = sd.get("audio_path")
        duration = sd.get("duration", 5.0)

        # Write image bytes to tmp file (MoviePy needs a path or numpy array)
        try:
            pil_img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
            pil_img = pil_img.resize((IMAGE_WIDTH, IMAGE_HEIGHT), PIL.Image.LANCZOS)
            img_arr = _pil_to_np(pil_img)
            clip = ImageClip(img_arr, duration=duration)
        except Exception as exc:
            st.warning(f"Scene {i+1} image decode failed, using black frame: {exc}")
            black = _pil_to_np(
                PIL.Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), (10, 10, 15))
            )
            clip = ImageClip(black, duration=duration)

        # Attach audio
        if audio_path and os.path.exists(audio_path):
            try:
                audio = AudioFileClip(audio_path).subclip(0, duration)
                clip = clip.set_audio(audio)
            except Exception as exc:
                st.warning(f"Scene {i+1} audio attach failed: {exc}")

        clips.append(clip)

    if not clips:
        st.error("No clips to assemble.")
        return False

    try:
        final = concatenate_videoclips(clips, method="compose")
        final.write_videofile(
            output_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=output_path.replace(".mp4", "_tmp_audio.m4a"),
            remove_temp=True,
            logger=None,
        )
        return True
    except Exception as exc:
        st.error(f"Video write failed: {exc}")
        return False
    finally:
        for c in clips:
            try:
                c.close()
            except Exception:
                pass


def _pil_to_np(pil_img):
    """Convert a PIL Image to a NumPy array (avoids importing numpy at top)."""
    import numpy as np
    return np.array(pil_img)


# ─────────────────────────────────────────────────────────────────────────────
#  5. SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "scenes": [],          # list of scene dicts from LLM
        "images": {},          # scene_number -> bytes
        "audios": {},          # scene_number -> filepath
        "durations": {},       # scene_number -> float
        "video_path": None,
        "pipeline_done": False,
        "is_running": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ─────────────────────────────────────────────────────────────────────────────
#  6. SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    st.markdown("---")

    art_style = st.selectbox(
        "Art Style",
        [
            "Cinematic photorealistic",
            "Watercolour illustration",
            "Dark fantasy oil painting",
            "Retro 80s synthwave",
            "Minimalist flat design",
            "Ink sketch / manga",
            "Isometric low-poly 3D",
            "Vintage travel poster",
        ],
    )

    max_scenes = st.slider("Max Scenes", min_value=2, max_value=10, value=5)

    tts_voice = st.selectbox(
        "TTS Voice",
        [
            "en-US-GuyNeural",
            "en-US-JennyNeural",
            "en-GB-RyanNeural",
            "en-GB-SoniaNeural",
            "en-AU-WilliamNeural",
        ],
    )

    st.markdown("---")
    st.markdown("### 🎭 Character")
    char_name = st.text_input("Character Name", placeholder="e.g. Atlas")
    char_desc = st.text_area(
        "Visual Description",
        placeholder="e.g. A tall astronaut in a worn orange suit, short silver hair, determined blue eyes",
        height=100,
    )

    st.markdown("---")
    st.markdown(
        "<small style='color:#555'>Powered by Pollinations.ai · edge-tts · MoviePy</small>",
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────────────────────────────────────
#  7. MAIN UI
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="app-header">
      <h1>🎬 Faceless Video Generator</h1>
      <p>Type a topic → get a fully narrated, AI-illustrated video — no API keys required.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

topic_col, btn_col = st.columns([5, 1], gap="small")
with topic_col:
    topic = st.text_input(
        "Video Topic",
        placeholder="e.g. What if the Earth stopped rotating?",
        label_visibility="collapsed",
    )
with btn_col:
    generate_btn = st.button("▶ Generate", use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
#  8. PIPELINE EXECUTION
# ─────────────────────────────────────────────────────────────────────────────
if generate_btn and topic and not st.session_state.is_running:
    # Reset state
    st.session_state.scenes = []
    st.session_state.images = {}
    st.session_state.audios = {}
    st.session_state.durations = {}
    st.session_state.video_path = None
    st.session_state.pipeline_done = False
    st.session_state.is_running = True

    # ── 8a. Generate script ───────────────────────────────────────────────
    with st.spinner("✍️  Writing script with Llama…"):
        scenes = generate_script(topic, art_style, max_scenes, char_name, char_desc)
    
    if not scenes:
        st.error("Script generation returned no scenes. Please try again.")
        st.session_state.is_running = False
        st.stop()

    st.session_state.scenes = scenes
    total = len(scenes)
    st.success(f"✅ Script ready — {total} scenes")

    # ── 8b. Per-scene: image + audio ─────────────────────────────────────
    progress_bar = st.progress(0, text="Starting pipeline…")
    status_placeholder = st.empty()

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, scene in enumerate(scenes):
            snum = scene.get("scene_number", idx + 1)
            narration = scene.get("narration_text", "")
            visual = scene.get("visual_prompt", "A beautiful landscape")

            progress_pct = idx / total
            progress_bar.progress(
                progress_pct,
                text=f"Scene {snum}/{total} — generating image…",
            )

            # Image
            status_placeholder.markdown(
                f'<span class="badge badge-pending">⏳ Scene {snum}: fetching image</span>',
                unsafe_allow_html=True,
            )
            img_bytes = generate_image(visual, snum, char_name, char_desc, art_style)
            if img_bytes is None:
                img_bytes = make_placeholder_frame()
                st.warning(f"Scene {snum}: using black placeholder frame.")
            st.session_state.images[snum] = img_bytes

            # Inter-request courtesy delay
            if idx < total - 1:
                time.sleep(IMAGE_INTER_REQUEST_DELAY)

            # Audio
            progress_bar.progress(
                (idx + 0.5) / total,
                text=f"Scene {snum}/{total} — synthesising audio…",
            )
            status_placeholder.markdown(
                f'<span class="badge badge-pending">⏳ Scene {snum}: generating audio</span>',
                unsafe_allow_html=True,
            )
            audio_path = os.path.join(tmpdir, f"scene_{snum}.mp3")
            ok = generate_audio(narration, audio_path, tts_voice)
            if ok and os.path.exists(audio_path):
                duration = get_audio_duration(audio_path)
                # Copy audio to a permanent temp file so MoviePy can read it
                perm_audio = tempfile.NamedTemporaryFile(
                    suffix=".mp3", delete=False, dir=tempfile.gettempdir()
                )
                perm_audio.write(open(audio_path, "rb").read())
                perm_audio.close()
                st.session_state.audios[snum] = perm_audio.name
                st.session_state.durations[snum] = duration
            else:
                st.warning(f"Scene {snum}: audio failed, using 5 s silent frame.")
                st.session_state.audios[snum] = None
                st.session_state.durations[snum] = 5.0

            progress_bar.progress(
                (idx + 1) / total,
                text=f"Scene {snum}/{total} ✓",
            )

        # ── 8c. Assemble video ────────────────────────────────────────────
        progress_bar.progress(1.0, text="🎞 Assembling video…")
        status_placeholder.markdown(
            '<span class="badge badge-pending">⏳ Rendering MP4…</span>',
            unsafe_allow_html=True,
        )

        video_tmp = tempfile.NamedTemporaryFile(
            suffix=".mp4", delete=False, dir=tempfile.gettempdir()
        )
        video_tmp.close()
        video_out = video_tmp.name

        scene_data_for_editor = []
        for idx, scene in enumerate(scenes):
            snum = scene.get("scene_number", idx + 1)
            scene_data_for_editor.append({
                "image_bytes": st.session_state.images.get(snum),
                "audio_path": st.session_state.audios.get(snum),
                "duration": st.session_state.durations.get(snum, 5.0),
            })

        success = assemble_video(scene_data_for_editor, video_out)
        if success:
            st.session_state.video_path = video_out
            st.session_state.pipeline_done = True
            status_placeholder.markdown(
                '<span class="badge badge-ok">✓ Video ready!</span>',
                unsafe_allow_html=True,
            )
        else:
            status_placeholder.markdown(
                '<span class="badge badge-err">✗ Video assembly failed</span>',
                unsafe_allow_html=True,
            )

    st.session_state.is_running = False

# ─────────────────────────────────────────────────────────────────────────────
#  9. RESULTS DISPLAY
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.scenes:
    st.markdown("---")
    st.markdown("## 🖼 Scene Gallery")

    scenes = st.session_state.scenes
    images = st.session_state.images

    # Display in a 2-column grid
    cols_per_row = 2
    for row_start in range(0, len(scenes), cols_per_row):
        row_scenes = scenes[row_start : row_start + cols_per_row]
        cols = st.columns(cols_per_row, gap="medium")
        for col, scene in zip(cols, row_scenes):
            snum = scene.get("scene_number", row_start + 1)
            narration = scene.get("narration_text", "")
            visual = scene.get("visual_prompt", "")
            img_bytes = images.get(snum)

            with col:
                if img_bytes:
                    st.image(img_bytes, use_container_width=True)
                else:
                    st.markdown(
                        '<div style="background:#0d0d0f;height:200px;border:1px dashed #333;'
                        'border-radius:8px;display:flex;align-items:center;justify-content:center;'
                        'color:#444">Generating…</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    f"""
                    <div class="scene-card">
                      <div class="scene-label">Scene {snum}</div>
                      <div class="scene-narration">{narration}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # ── ZIP download ──────────────────────────────────────────────────────
    if images:
        st.markdown("---")
        col_zip, col_spacer = st.columns([1, 3])
        with col_zip:
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for snum, img_bytes in images.items():
                    if img_bytes:
                        zf.writestr(f"scene_{snum:02d}.png", img_bytes)
            zip_buf.seek(0)
            st.download_button(
                label="⬇ Download All Frames (ZIP)",
                data=zip_buf,
                file_name="faceless_video_frames.zip",
                mime="application/zip",
                use_container_width=True,
            )

# ─────────────────────────────────────────────────────────────────────────────
#  10. VIDEO PLAYER
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.pipeline_done and st.session_state.video_path:
    video_path = st.session_state.video_path
    if os.path.exists(video_path):
        st.markdown("---")
        st.markdown("## 🎬 Final Video")

        video_bytes = open(video_path, "rb").read()
        st.video(video_bytes)

        st.download_button(
            label="⬇ Download MP4",
            data=video_bytes,
            file_name=f"faceless_video_{int(time.time())}.mp4",
            mime="video/mp4",
        )
    else:
        st.warning("Video file not found — it may have been cleaned up. Please regenerate.")

# ─────────────────────────────────────────────────────────────────────────────
#  11. EMPTY STATE
# ─────────────────────────────────────────────────────────────────────────────
if not st.session_state.scenes and not st.session_state.is_running:
    st.markdown(
        """
        <div style="text-align:center;padding:60px 20px;color:#3a3a5a">
          <div style="font-size:3.5rem;margin-bottom:16px">🎬</div>
          <p style="font-size:1rem;font-family:'Space Mono',monospace">
            Enter a topic above and press <strong style="color:#e94560">▶ Generate</strong>
            to create your faceless video.
          </p>
          <p style="font-size:0.78rem;margin-top:12px;color:#2a2a4a">
            Script → Images → Voiceover → MP4 — all free, no keys required.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
