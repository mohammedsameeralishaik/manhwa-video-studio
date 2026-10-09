# Manhwa Video Studio 🎬

A modern, cinematic web studio that turns **manhwa/webtoon chapters** into **16:9 YouTube Widescreen** and **9:16 Vertical (Shorts / Reels / TikTok)** videos with professional Ken Burns camera motion and seamless transitions.

---

## ✨ Features

- **Dual Video Formats**:
  - **16:9 YouTube Landscape**: Full character body & face preserved with elegant Gaussian blur wings.
  - **9:16 Vertical**: Optimized for YouTube Shorts, Instagram Reels, and TikTok.
- **Smart Natural Boundary Detection**:
  - Automatically slices continuous webtoon rolls into balanced scenes without cutting through characters, faces, or speech bubbles using gradient edge energy analysis.
- **Camera Motion Modes (Per Scene)**:
  - 🖼️ **Pillarbox Blur (Default)**: Full artwork centered with blurred background wings.
  - 🎬 **Vertical Pan**: Camera glides smoothly from character's face/head down to feet.
  - 🔍 **Dialogue & Face Zoom**: Magnifies speech bubbles (1.35×) for clear readability on YouTube monitors.
- **Scene Director & 16:9 Live Preview**:
  - Preview camera motions and dialogue framing in real-time in the browser before rendering.
- **Flexible Import**:
  - URL Scraper for web readers.
  - Local Upload / Drag-and-drop for chapter images (JPG, PNG, WEBP) or full `.zip` archives (100% offline).
- **Cinematic Transitions & Pacing**:
  - Mix, Fade, Dissolve, Slides, Wipe, and Circle reveal.
  - Adjustable pacing per panel (0.5s – 10s) and transition overlap.
- **One-Click Export**:
  - Instant browser video preview.
  - Download MP4 master video + full Project ZIP (with original panels, formatted crops, and settings).
- **Google Colab Support**:
  - Includes a 1-click `Manhwa_Video_Studio_Colab.ipynb` notebook to run on Google's cloud with free GPU/CPU and an instant Cloudflare tunnel.

---

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.9+
- **FFmpeg** on your PATH

### Setup
```bash
git clone https://github.com/mohammedsameeralishaik/manhwa-video-studio.git
cd manhwa-video-studio

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run studio
uvicorn app:app --host 127.0.0.1 --port 8000
```
Then open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

> **Windows Users**: You can also simply double-click `run.bat` to launch!

---

## ☁️ Run in Google Colab (Free Cloud VM)

Open **[`Manhwa_Video_Studio_Colab.ipynb`](Manhwa_Video_Studio_Colab.ipynb)** in Google Colab:
1. Run the dependency cell (`!apt-get install -y ffmpeg && pip install -r requirements.txt`).
2. Run the launcher cell to get an instant public HTTPS link (`https://xxxx.trycloudflare.com`).
3. Open the link on any PC, phone, or tablet!

---

## 🛠️ Tech Stack

- **Backend**: FastAPI, Uvicorn, Pillow, NumPy, Requests
- **Video Engine**: FFmpeg with `zoompan` and `xfade` filter complex
- **Frontend**: Modern Vanilla JS, CSS3 Design System with responsive 16:9 Cinema Monitor
