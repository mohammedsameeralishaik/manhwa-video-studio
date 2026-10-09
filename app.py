#!/usr/bin/env python3
"""
Manhwa Video Studio - backend.

Paste a manhwa chapter URL -> extract page images -> select / order them ->
9:16 crops -> cinematic Ken Burns + transition video -> MP4 + ZIP download.

Run:
    pip install -r requirements.txt
    uvicorn app:app --host 127.0.0.1 --port 8000
Then open http://127.0.0.1:8000 in a browser.

Requires ffmpeg on PATH for video rendering.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

# Ensure Gyan FFmpeg is in PATH if installed on Windows
FFMPEG_DIR = r"C:\Users\Sameerali\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.1-essentials_build\bin"
if os.path.exists(FFMPEG_DIR) and FFMPEG_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

import numpy as np
import requests
from typing import List
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageFilter
from pydantic import BaseModel

ROOT = Path(__file__).parent
JOBS = ROOT / "jobs"
JOBS.mkdir(exist_ok=True)

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
}

TRANSITIONS = {
    "mix": "Cinematic mix",
    "fade": "Fade",
    "dissolve": "Dissolve",
    "smoothleft": "Slide left",
    "smoothright": "Slide right",
    "smoothup": "Slide up",
    "smoothdown": "Slide down",
    "wipeleft": "Wipe",
    "circlecrop": "Circle reveal",
}
MIX_ORDER = ["smoothleft", "smoothright", "smoothup", "smoothdown",
             "circlecrop", "fade", "dissolve", "wipeleft"]
RESOLUTIONS = {
    # 9:16 Vertical (Shorts, Reels, TikTok)
    "1080x1920": (1080, 1920),
    "720x1280": (720, 1280),
    "1440x2560": (1440, 2560),
    # 16:9 Landscape (YouTube Standard, Desktop)
    "1920x1080": (1920, 1080),
    "1280x720": (1280, 720),
    "2560x1440": (2560, 1440),
}
CROP_MODES = {"scene_split": "Smart scene split (natural gutters)",
              "blur_fill": "Fit full image (blurred background)",
              "center_crop": "Center crop"}
SCENE_MODES = {
    "blur_fill": "Pillarbox Blur (Default - full character with blurred wings)",
    "vpan": "Vertical Pan (Face to Feet glide for tall panels)",
    "dialogue": "Dialogue & Face Zoom (Enlarge text & bubbles for readability)"
}
CHUNK = 12  # max inputs per ffmpeg filter graph (memory safety)

app = FastAPI(title="Manhwa Video Studio")
_state, _lock = {}, threading.Lock()


def set_status(jid, **kw):
    with _lock:
        _state.setdefault(jid, {}).update(kw)


def get_status(jid):
    with _lock:
        return dict(_state.get(jid, {}))


def job_paths(jid):
    base = JOBS / jid
    return {
        "base": base,
        "originals": base / "originals",
        "processed": base / "processed",
        "video": base / "video",
        "meta": base / "meta.json",
    }


# ---------------------------------------------------------------- request models
class ExtractReq(BaseModel):
    url: str
    consent: bool = False


class ProcessReq(BaseModel):
    selection: list  # original image ids, in order
    crop_mode: str = "scene_split"
    resolution: str = "1080x1920"


class RenderReq(BaseModel):
    order: list  # processed image ids, in order
    scene_modes: dict = {}  # { "p001": "blur_fill" | "vpan" | "dialogue" }
    per_image: float = 2.0
    trans_duration: float = 0.6
    transition: str = "mix"
    zoom: float = 1.15
    zoom_mode: str = "alternate"  # in | out | alternate | none
    resolution: str = "1080x1920"
    fps: int = 30


# ---------------------------------------------------------------- extraction
def find_image_urls(html):
    """Manhwa chapter image URLs. Tries known CDN patterns, then <img> fallback."""
    urls = re.findall(
        r"https://cdn\.asurascans\.com/asura-images/chapters/"
        r"[^\"'\s]+?/\d+/[^\"'?\s]+\.webp\?v=\d+", html)
    if not urls:
        imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html)
        urls = [u for u in imgs
                if u.startswith("http")
                and not re.search(r"(logo|icon|avatar|banner|advert|ads?[/.])", u, re.I)]
    return list(dict.fromkeys(urls))


def extract_worker(jid, url):
    p = job_paths(jid)
    try:
        set_status(jid, stage="extracting", progress=4,
                   message="Fetching page…")
        try:
            html = requests.get(url, headers=UA, timeout=40).text
        except Exception:
            raise RuntimeError(
                "Could not load that URL (network error or site blocked the request).")
        urls = find_image_urls(html)
        if not urls:
            raise RuntimeError(
                "No readable images found on that page. The site may be "
                "unsupported or blocking automated access.")
        p["originals"].mkdir(parents=True, exist_ok=True)
        saved = []
        for i, u in enumerate(urls):
            try:
                r = requests.get(u, headers={**UA, "Referer": "https://asurascans.com/"},
                                 timeout=60)
                r.raise_for_status()
                if len(r.content) < 15000:
                    continue
                ext = ".webp" if ".webp" in u else (
                    ".png" if ".png" in u else ".jpg")
                name = f"img{i + 1:03d}{ext}"
                (p["originals"] / name).write_bytes(r.content)
                with Image.open(p["originals"] / name) as im:
                    w, h = im.size
                saved.append({"id": f"img{i + 1:03d}", "file": name,
                              "width": w, "height": h})
            except Exception:
                continue
            set_status(jid, progress=int(4 + 92 * (i + 1) / len(urls)),
                       message=f"Downloaded {i + 1}/{len(urls)} images…")
        if not saved:
            raise RuntimeError(
                "Images were found but none could be downloaded — the site "
                "may block automated access.")
        p["meta"].write_text(json.dumps(
            {"url": url, "images": saved, "created": time.time()}))
        set_status(jid, stage="ready", progress=100,
                   message=f"{len(saved)} images ready", images=saved)
    except Exception as e:
        set_status(jid, stage="error", message=str(e))


# ---------------------------------------------------------------- 9:16 & 16:9 processing
def blur_fill(im, W, H, margin=0.96):
    """
    Fits full character and panel artwork inside (W, H) with no clipping.
    Background is a cinematic dimmed Gaussian blur of the artwork.
    margin=0.96 provides 4% safe padding so Ken Burns motion never cuts off the face or feet.
    """
    # Create background: scale artwork to cover (W, H), blur, and dim slightly for contrast
    scale_bg = max(W / max(1, im.width), H / max(1, im.height))
    bg_w, bg_h = int(im.width * scale_bg + 0.5), int(im.height * scale_bg + 0.5)
    bg = im.resize((bg_w, bg_h), Image.LANCZOS)
    bg_x = max(0, (bg_w - W) // 2)
    bg_y = max(0, (bg_h - H) // 2)
    bg = bg.crop((bg_x, bg_y, bg_x + W, bg_y + H))
    bg = bg.filter(ImageFilter.GaussianBlur(38))
    # Dim background slightly so the centered character artwork pops
    bg = Image.blend(bg, Image.new("RGB", (W, H), (12, 14, 20)), 0.35)

    # Foreground: fit completely inside target box with margin
    max_w = int(W * margin)
    max_h = int(H * margin)
    scale_fg = min(max_w / max(1, im.width), max_h / max(1, im.height))
    fg_w = max(1, int(im.width * scale_fg + 0.5))
    fg_h = max(1, int(im.height * scale_fg + 0.5))
    fg = im.resize((fg_w, fg_h), Image.LANCZOS)

    # Paste in center
    pos_x = (W - fg_w) // 2
    pos_y = (H - fg_h) // 2
    bg.paste(fg, (pos_x, pos_y))
    return [bg]


def center_crop(im, W, H):
    scale = max(W / im.width, H / im.height)
    im2 = im.resize((int(im.width * scale + 0.5),
                     int(im.height * scale + 0.5)), Image.LANCZOS)
    x, y = (im2.width - W) // 2, (im2.height - H) // 2
    return [im2.crop((x, y, x + W, y + H))]


def find_best_cut_y(a_lum, target_y, h_total, min_search, max_search):
    """
    Finds the optimal vertical cut line that avoids slicing through
    characters, faces, or speech bubbles by minimizing edge energy
    and texture variance within [min_search, max_search].
    """
    min_y = max(5, int(min_search))
    max_y = min(h_total - 5, int(max_search))
    if min_y >= max_y:
        return int(target_y)

    sub_a = a_lum[min_y:max_y + 1, :]
    r_std = sub_a.std(axis=1)

    prev_rows = a_lum[min_y - 1:max_y, :]
    diff_mean = np.abs(sub_a - prev_rows).mean(axis=1)

    r_mean = sub_a.mean(axis=1)
    is_gutter = ((r_mean > 240) & (r_std < 15)) | ((r_mean < 25) & (r_std < 12))

    y_indices = np.arange(min_y, max_y + 1)
    dist_penalty = (np.abs(y_indices - target_y) / max(1, (max_y - min_y))) * 25.0

    scores = r_std + (diff_mean * 3.5) + dist_penalty
    scores[is_gutter] -= 1000.0

    best_idx = np.argmin(scores)
    return int(y_indices[best_idx])


def split_scenes(im, W=1080, H=1920):
    """
    Split a tall manhwa page or unbroken webtoon roll into sequential scene crops.
    Uses edge-energy and variance analysis (find_best_cut_y) to avoid cutting
    through faces, characters, and dialogue bubbles.
    Returns list of tuples: (formatted_image_with_blur_fill, raw_panel_image).
    """
    NW = 900
    w, h = im.size
    if w != NW:
        im = im.resize((NW, int(h * NW / w)), Image.LANCZOS)
        w, h = im.size
    CH = max(120, int(round(NW * H / W)))
    a = np.asarray(im.convert("L"), dtype=np.float32)
    row_mean, row_std = a.mean(axis=1), a.std(axis=1)

    # Detect both light (white) and dark (black) manhwa gutters
    is_gap = ((row_mean > 245) & (row_std < 15)) | ((row_mean < 18) & (row_std < 12))

    scenes, in_s, s = [], False, 0
    for y in range(h):
        if not is_gap[y] and not in_s:
            in_s, s = True, y
        elif is_gap[y] and in_s:
            in_s = False
            scenes.append((s, y))
    if in_s:
        scenes.append((s, h))

    min_cut = max(90, int(min(NW, CH) * 0.2))
    scenes = [(s, e) for s, e in scenes if e - s >= min_cut]
    kept = []
    for s, e in scenes:
        seg = a[s:e]
        if (seg.mean() > 251 and seg.std() < 6) or (seg.mean() < 8 and seg.std() < 5):
            continue
        kept.append((s, e))

    if not kept:
        return [(blur_fill(im, W, H)[0], im)]

    is_landscape = W > H
    out = []

    for s, e in kept:
        sh = e - s
        if is_landscape:
            # 16:9 YouTube format (W > H)
            # If panel fits nicely in 16:9 (height up to 2.2x width):
            if sh <= int(NW * 2.2):
                panel = im.crop((0, s, NW, e))
                out.append((blur_fill(panel, W, H)[0], panel))
            else:
                # Continuous uncut roll: segment at natural visual boundaries
                target_h = int(NW * 1.35)
                y = s
                while y < e:
                    rem = e - y
                    if rem <= int(target_h * 1.35):
                        sub_panel = im.crop((0, y, NW, e))
                        out.append((blur_fill(sub_panel, W, H)[0], sub_panel))
                        break
                    min_s = y + int(target_h * 0.65)
                    max_s = min(e - int(target_h * 0.35), y + int(target_h * 1.35))
                    cut_y = find_best_cut_y(a, y + target_h, h, min_s, max_s)
                    sub_panel = im.crop((0, y, NW, cut_y))
                    out.append((blur_fill(sub_panel, W, H)[0], sub_panel))
                    y = cut_y
        else:
            # 9:16 Vertical format (W < H)
            if sh <= int(CH * 1.3):
                panel = im.crop((0, s, NW, e))
                out.append((blur_fill(panel, W, H)[0], panel))
            else:
                # Tall continuous roll in vertical mode: cut at natural boundaries around CH
                y = s
                while y < e:
                    rem = e - y
                    if rem <= int(CH * 1.35):
                        sub_panel = im.crop((0, y, NW, e))
                        out.append((blur_fill(sub_panel, W, H)[0], sub_panel))
                        break
                    min_s = y + int(CH * 0.65)
                    max_s = min(e - int(CH * 0.35), y + int(CH * 1.35))
                    cut_y = find_best_cut_y(a, y + CH, h, min_s, max_s)
                    sub_panel = im.crop((0, y, NW, cut_y))
                    out.append((blur_fill(sub_panel, W, H)[0], sub_panel))
                    y = cut_y

    return out if out else [(blur_fill(im, W, H)[0], im)]


def to_crop_format(im, W, H, mode):
    w, h = im.size
    if mode == "blur_fill" or (mode == "scene_split" and w > h):
        return [(blur_fill(im, W, H)[0], im)]
    if mode == "center_crop":
        return [(center_crop(im, W, H)[0], im)]
    return split_scenes(im, W, H)

to_916 = to_crop_format


def process_worker(jid, selection, crop_mode, resolution):
    p = job_paths(jid)
    try:
        W, H = RESOLUTIONS.get(resolution, (1080, 1920))
        if crop_mode not in CROP_MODES:
            crop_mode = "scene_split"
        meta = json.loads(p["meta"].read_text())
        by_id = {img["id"]: img for img in meta["images"]}
        outdir = p["processed"]
        if outdir.exists():
            shutil.rmtree(outdir)
        outdir.mkdir(parents=True)
        processed, k = [], 0
        total = len(selection)
        for n, iid in enumerate(selection):
            info = by_id.get(iid)
            if not info:
                continue
            with Image.open(p["originals"] / info["file"]) as im:
                im = im.convert("RGB")
                crops = to_916(im, W, H, crop_mode)
            for c, raw_p in crops:
                k += 1
                name = f"p{k:03d}.jpg"
                raw_name = f"p{k:03d}_raw.jpg"
                c.save(outdir / name, quality=90)
                raw_p.save(outdir / raw_name, quality=90)
                is_tall = (raw_p.height / max(1, raw_p.width)) >= 1.15
                processed.append({
                    "id": f"p{k:03d}",
                    "file": name,
                    "raw_file": raw_name,
                    "from": iid,
                    "is_tall": is_tall,
                    "aspect": round(raw_p.height / max(1, raw_p.width), 2),
                    "mode": "blur_fill"
                })
            set_status(jid, stage="processing",
                       progress=int(100 * (n + 1) / total),
                       message=f"Processed {n + 1}/{total} images…")
        if not processed:
            raise RuntimeError("No images could be processed.")
        meta["processed"] = processed
        meta["crop_mode"] = crop_mode
        meta["resolution"] = resolution
        p["meta"].write_text(json.dumps(meta))
        set_status(jid, stage="processed", progress=100,
                   message=f"{len(processed)} frames ready",
                   processed=processed)
    except Exception as e:
        set_status(jid, stage="error", message=str(e))


# ---------------------------------------------------------------- video rendering & hardware acceleration
_GPU_ENCODER = None


def get_video_encoder():
    """
    Detects if NVIDIA NVENC hardware acceleration is genuinely available (e.g. in Colab T4 GPU).
    Falls back to multi-threaded CPU ultrafast encoding using all available cores.
    """
    global _GPU_ENCODER
    if _GPU_ENCODER is not None:
        return _GPU_ENCODER

    try:
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
               "-c:v", "h264_nvenc", "-f", "null", "-"]
        res = subprocess.run(cmd, capture_output=True, timeout=3)
        if res.returncode == 0:
            _GPU_ENCODER = ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "20"])
            return _GPU_ENCODER
    except Exception:
        pass

    # High-speed multi-threaded CPU fallback: max core utilization & ultrafast preset
    _GPU_ENCODER = ("libx264", ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-threads", "0"])
    return _GPU_ENCODER


def clip_filter(i, W, H, per_image, fps, zoom, zoom_mode, mode="blur_fill"):
    frames = int(round(per_image * fps))
    if mode == "vpan":
        # Raw unpadded panel: scale width to W, pad height if needed, and glide from face (top) to feet (bottom)
        return (
            f"[{i}:v]scale={W}:-2,pad={W}:max(ih\\,{H}):0:0,"
            f"zoompan=z=1:x=0:y='max(0, (ih-{H})*(on/max(1, {frames}-1)))':"
            f"d={frames}:s={W}x{H}:fps={fps},setsar=1,format=yuv420p[v{i}]"
        )
    elif mode == "dialogue":
        # Anchor zoom towards top 18% where dialogue bubbles and faces are situated
        return (
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"zoompan=z='1.35':x='(iw-iw/zoom)/2':y='max(0, (ih-ih/zoom)*0.18)':"
            f"d={frames}:s={W}x{H}:fps={fps},setsar=1,format=yuv420p[v{i}]"
        )
    else:  # blur_fill (default pillarbox with blurred wings)
        m = zoom_mode
        if m == "alternate":
            m = "in" if i % 2 == 0 else "out"
        if m == "none" or zoom <= 1.0 or frames < 2:
            z = "1"
        elif m == "in":
            z = f"1+({zoom}-1)*on/{frames - 1}"
        else:
            z = f"{zoom}-({zoom}-1)*on/{frames - 1}"
        # Optimized scale: 1.25x provides crisp subpixel anti-aliasing without 4K overhead
        scale_w = int(W * 1.25) // 2 * 2
        scale_h = int(H * 1.25) // 2 * 2
        return (
            f"[{i}:v]scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
            f"crop={scale_w}:{scale_h},"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={W}x{H}:fps={fps},setsar=1,format=yuv420p[v{i}]"
        )


def build_chunk(items, out_path, W, H, per_image, fps, zoom, zoom_mode,
                trans_list, start_idx):
    n = len(items)
    args = ["ffmpeg", "-y", "-threads", "0"]
    # NOTE: feed each image as a SINGLE frame (no -loop). zoompan's d=
    # expands that one frame to exactly per_image seconds.
    for f, m in items:
        args += ["-i", f]
    fc = [clip_filter(i, W, H, per_image, fps, zoom, zoom_mode, mode=items[i][1])
          for i in range(n)]
    dur, last = per_image, "v0"
    for i in range(1, n):
        t = trans_list[(start_idx + i - 1) % len(trans_list)]
        offset = dur - TD[0]
        fc.append(f"[{last}][v{i}]xfade=transition={t}:duration={TD[0]:.3f}"
                  f":offset={offset:.3f}[x{i}]")
        last, dur = f"x{i}", dur + per_image - TD[0]
    
    _, enc_flags = get_video_encoder()
    args += ["-filter_complex", ";".join(fc), "-map", f"[{last}]"] + enc_flags + ["-an", out_path]
    subprocess.run(args, check=True, capture_output=True)
    return dur


TD = [0.6]  # transition duration slot (set per render)


def render_video(items, out_path, W, H, per_image, fps, zoom, zoom_mode,
                 trans_list, trans_dur, progress_cb=None):
    TD[0] = trans_dur
    n = len(items)
    if n == 1:
        build_chunk(items, out_path, W, H, per_image, fps, zoom, zoom_mode,
                    trans_list, 0)
        return
    chunks, i = [], 0
    while i < n:
        j = min(i + CHUNK, n)
        chunks.append((items[i:j], i))
        if j == n:
            break
        i = j - 1
    tmpdir = tempfile.mkdtemp(prefix="mvs_chunks_")
    try:
        cpaths = []
        for k, (cf, sidx) in enumerate(chunks):
            cp = str(Path(tmpdir) / f"c{k}.mp4")
            build_chunk(cf, cp, W, H, per_image, fps, zoom, zoom_mode,
                        trans_list, sidx)
            cpaths.append(cp)
            if progress_cb:
                progress_cb(int(90 * (k + 1) / len(chunks)))
        trim = per_image - trans_dur
        args = ["ffmpeg", "-y", "-threads", "0"]
        for cp in cpaths:
            args += ["-i", cp]
        fc = []
        for k in range(len(cpaths)):
            if k == 0:
                fc.append(f"[{k}:v]setpts=PTS-STARTPTS,format=yuv420p[j{k}]")
            else:
                fc.append(f"[{k}:v]trim=start={trim:.3f},"
                          f"setpts=PTS-STARTPTS,format=yuv420p[j{k}]")
        ins = "".join(f"[j{k}]" for k in range(len(cpaths)))
        fc.append(f"{ins}concat=n={len(cpaths)}:v=1:a=0[out]")
        
        _, enc_flags = get_video_encoder()
        args += ["-filter_complex", ";".join(fc), "-map", "[out]"] + enc_flags + [
            "-movflags", "+faststart", "-an", out_path
        ]
        subprocess.run(args, check=True, capture_output=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def render_worker(jid, order, scene_modes, per_image, trans_duration, transition,
                  zoom, zoom_mode, resolution, fps):
    p = job_paths(jid)
    try:
        W, H = RESOLUTIONS.get(resolution, (1080, 1920))
        meta = json.loads(p["meta"].read_text())
        by_id = {img["id"]: img for img in meta.get("processed", [])}
        items = []
        for i in order:
            if i not in by_id:
                continue
            entry = by_id[i]
            mode = (scene_modes or {}).get(i, "blur_fill")
            if mode in ("vpan", "dialogue"):
                raw_file = entry.get("raw_file", entry["file"])
                raw_path = p["processed"] / raw_file
                fpath = str(raw_path if raw_path.exists() else p["processed"] / entry["file"])
            else:
                fpath = str(p["processed"] / entry["file"])
            items.append((fpath, mode))

        if not items:
            raise RuntimeError("No processed images selected for the video.")
        per_image = max(0.5, min(10.0, float(per_image)))
        trans_dur = max(0.1, min(float(trans_duration), per_image - 0.1))
        zoom = max(1.0, min(1.5, float(zoom)))
        fps = int(fps) if int(fps) in (24, 25, 30, 60) else 30
        trans_list = MIX_ORDER if transition == "mix" else [transition]
        outdir = p["video"]
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / "video_render.mp4"

        def cb(pct):
            set_status(jid, stage="rendering", progress=pct,
                       message=f"Rendering video… {pct}%")
        set_status(jid, stage="rendering", progress=2,
                   message="Rendering video…")
        render_video(items, str(out), W, H, per_image, fps, zoom,
                     zoom_mode, trans_list, trans_dur, progress_cb=cb)
        shutil.copy2(str(out), str(outdir / "video_9x16.mp4"))
        meta["render"] = {"order": order, "scene_modes": scene_modes or {},
                          "per_image": per_image,
                          "trans_duration": trans_dur,
                          "transition": transition, "zoom": zoom,
                          "zoom_mode": zoom_mode, "resolution": resolution,
                          "fps": fps, "frames": len(items)}
        p["meta"].write_text(json.dumps(meta))
        set_status(jid, stage="done", progress=100,
                   message="Video ready", video="video_render.mp4")
    except subprocess.CalledProcessError:
        set_status(jid, stage="error",
                   message="Video rendering failed (ffmpeg error). Try fewer "
                           "images or a lower resolution.")
    except Exception as e:
        set_status(jid, stage="error", message=str(e))


# ---------------------------------------------------------------- ZIP
README_TXT = """Manhwa Video Studio - project export
=====================================
This archive was generated by Manhwa Video Studio.

Contents:
  originals/        - page images extracted from the source, as downloaded
  processed_frames/ - vertical (9:16) or landscape (16:9) frames in video order
  video_render.mp4  - the finished silent video
  project.json      - project settings (selection, order, transitions, zoom)

Notes:
- The video contains no audio by design (ready for YouTube Shorts, Reels,
  TikTok or full YouTube landscape - add your own soundtrack in your editor).
- Only process content you are authorized to download and use.
"""


def build_zip(jid):
    p = job_paths(jid)
    meta = json.loads(p["meta"].read_text())
    zpath = p["base"] / "project.zip"
    if zpath.exists():
        zpath.unlink()
    order = (meta.get("render") or {}).get("order", [])
    by_id = {img["id"]: img for img in meta.get("processed", [])}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for img in meta.get("images", []):
            fp = p["originals"] / img["file"]
            if fp.exists():
                z.write(fp, f"originals/{img['file']}")
        for i, pid in enumerate(order):
            info = by_id.get(pid)
            if info and (p["processed"] / info["file"]).exists():
                z.write(p["processed"] / info["file"],
                        f"processed_frames/{i + 1:03d}_{info['file']}")
        v = p["video"] / "video_render.mp4"
        if not v.exists():
            v = p["video"] / "video_9x16.mp4"
        if v.exists():
            z.write(v, "video_render.mp4")
        z.writestr("project.json", json.dumps(meta, indent=2))
        z.writestr("README.txt", README_TXT)
    return zpath


# ---------------------------------------------------------------- API routes
@app.post("/api/extract")
def api_extract(req: ExtractReq):
    url = (req.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "Please paste a valid http(s) URL."},
                            status_code=400)
    if not req.consent:
        return JSONResponse(
            {"error": "Please confirm you are authorized to download images "
                      "from this URL."}, status_code=400)
    jid = uuid.uuid4().hex[:12]
    set_status(jid, stage="extracting", progress=0,
               message="Starting…", url=url)
    threading.Thread(target=extract_worker, args=(jid, url),
                     daemon=True).start()
    return {"job_id": jid}


@app.post("/api/upload")
async def api_upload(files: List[UploadFile] = File(...)):
    if not files:
        return JSONResponse({"error": "No files provided."}, status_code=400)
    jid = uuid.uuid4().hex[:12]
    p = job_paths(jid)
    p["originals"].mkdir(parents=True, exist_ok=True)
    saved = []
    idx = 1
    import io
    for f in files:
        filename = (f.filename or "").lower()
        content = await f.read()
        if not content:
            continue
        if filename.endswith(".zip") or (len(content) > 4 and content[:4] == b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for zname in sorted(zf.namelist()):
                        zlower = zname.lower()
                        if any(zlower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                            raw = zf.read(zname)
                            if len(raw) < 1000:
                                continue
                            ext = Path(zname).suffix.lower() or ".jpg"
                            img_name = f"img{idx:03d}{ext}"
                            dest = p["originals"] / img_name
                            dest.write_bytes(raw)
                            try:
                                with Image.open(dest) as im:
                                    w, h = im.size
                                saved.append({"id": f"img{idx:03d}", "file": img_name, "width": w, "height": h})
                                idx += 1
                            except Exception:
                                dest.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        if not any(filename.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            continue
        if len(content) < 1000:
            continue
        ext = Path(f.filename).suffix.lower() or ".jpg"
        img_name = f"img{idx:03d}{ext}"
        dest = p["originals"] / img_name
        dest.write_bytes(content)
        try:
            with Image.open(dest) as im:
                w, h = im.size
            saved.append({"id": f"img{idx:03d}", "file": img_name, "width": w, "height": h})
            idx += 1
        except Exception:
            dest.unlink(missing_ok=True)
            continue
    if not saved:
        return JSONResponse({"error": "No valid images found. Upload JPG, PNG, WEBP files or a ZIP."}, status_code=400)
    p["meta"].write_text(json.dumps({"url": "Local Upload", "images": saved, "created": time.time()}))
    set_status(jid, stage="ready", progress=100, message=f"{len(saved)} images ready", images=saved)
    return {"job_id": jid, "count": len(saved)}


@app.get("/api/jobs/{jid}")
def api_job(jid: str):
    s = get_status(jid)
    if not s:
        return JSONResponse({"error": "Unknown job."}, status_code=404)
    return s


@app.post("/api/jobs/{jid}/process")
def api_process(jid: str, req: ProcessReq):
    if not get_status(jid):
        return JSONResponse({"error": "Unknown job."}, status_code=404)
    if not req.selection:
        return JSONResponse({"error": "Select at least one image."},
                            status_code=400)
    set_status(jid, stage="processing", progress=0, message="Starting…")
    threading.Thread(target=process_worker,
                     args=(jid, req.selection, req.crop_mode, req.resolution),
                     daemon=True).start()
    return {"ok": True}


@app.post("/api/jobs/{jid}/render")
def api_render(jid: str, req: RenderReq):
    if not get_status(jid):
        return JSONResponse({"error": "Unknown job."}, status_code=404)
    if not req.order:
        return JSONResponse({"error": "No frames selected for the video."},
                            status_code=400)
    if req.transition not in TRANSITIONS:
        return JSONResponse({"error": "Unknown transition."}, status_code=400)
    set_status(jid, stage="rendering", progress=0, message="Starting…")
    threading.Thread(target=render_worker,
                     args=(jid, req.order, req.scene_modes, req.per_image, req.trans_duration,
                           req.transition, req.zoom, req.zoom_mode,
                           req.resolution, req.fps),
                     daemon=True).start()
    return {"ok": True}


@app.get("/api/file/{jid}/{kind}/{name}")
def api_file(jid: str, kind: str, name: str):
    p = job_paths(jid)
    if kind not in ("originals", "processed"):
        return JSONResponse({"error": "Not found."}, status_code=404)
    fp = (p[kind] / name).resolve()
    base = p[kind].resolve()
    if not str(fp).startswith(str(base)) or not fp.exists():
        return JSONResponse({"error": "Not found."}, status_code=404)
    return FileResponse(fp)


@app.get("/api/video/{jid}")
def api_video(jid: str):
    vdir = job_paths(jid)["video"]
    fp = vdir / "video_render.mp4"
    if not fp.exists():
        fp = vdir / "video_9x16.mp4"
    if not fp.exists():
        return JSONResponse({"error": "Video not ready."}, status_code=404)
    return FileResponse(fp, media_type="video/mp4")


@app.get("/api/download/video/{jid}")
def api_dl_video(jid: str):
    vdir = job_paths(jid)["video"]
    fp = vdir / "video_render.mp4"
    if not fp.exists():
        fp = vdir / "video_9x16.mp4"
    if not fp.exists():
        return JSONResponse({"error": "Video not ready."}, status_code=404)
    return FileResponse(fp, media_type="video/mp4",
                        filename="manhwa_video.mp4")


@app.get("/api/download/zip/{jid}")
def api_dl_zip(jid: str):
    try:
        zpath = build_zip(jid)
    except Exception as e:
        return JSONResponse({"error": f"ZIP failed: {e}"}, status_code=500)
    return FileResponse(zpath, media_type="application/zip",
                        filename="manhwa_video_project.zip")


@app.get("/api/options")
def api_options():
    return {
        "transitions": TRANSITIONS,
        "resolutions": {
            k: {
                "label": k.replace("x", " × "),
                "width": v[0],
                "height": v[1],
                "ratio": "9:16" if v[0] < v[1] else "16:9",
                "tag": "Shorts / Reels (9:16)" if v[0] < v[1] else "YouTube Landscape (16:9)"
            }
            for k, v in RESOLUTIONS.items()
        },
        "crop_modes": CROP_MODES,
        "scene_modes": SCENE_MODES
    }


app.mount("/", StaticFiles(directory=str(ROOT / "static"), html=True),
          name="static")
