#!/usr/bin/env python3
"""
app.py - FastAPI web frontend for SEO Blog Automation

Wraps seobot_ai, social_posts_generator, podcast_generator,
and wordpress_sync as API endpoints with a modern dashboard UI.
"""

import os
import sys
import json
import asyncio
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

# Fix Windows console encoding before any print/log with emojis
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass

try:
    from dotenv import load_dotenv
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from pydantic import BaseModel
except ModuleNotFoundError as e:
    missing = (e.name or "dotenv").strip()
    print("Missing dependency:", missing, "-> installing into current Python...")
    import subprocess
    req_file = Path(__file__).parent / "requirements.txt"
    if req_file.exists():
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)], stdout=sys.stdout, stderr=sys.stderr)
    else:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "python-dotenv", "fastapi", "uvicorn[standard]", "jinja2", "python-multipart"], stdout=sys.stdout, stderr=sys.stderr)
    print("Done. Restarting...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

load_dotenv()

logger = logging.getLogger("blog-app")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    logger.addHandler(_handler)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

app = FastAPI(title="SEO Blog Automation Dashboard")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.middleware("http")
async def log_requests(request: Request, call_next):
    import time
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    if request.url.path.startswith("/api"):
        logger.info("%s %s  -> %d  (%.0fms)", request.method, request.url.path, response.status_code, elapsed)
    return response


# --------------- Lazy module helpers ---------------

_supabase_client = None

def _get_supabase():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase_client


def _run_in_thread(fn, *args, **kwargs):
    """Run a blocking function in a thread pool so we don't block the event loop."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


# --------------- Pydantic models ---------------

class BlogGenerateRequest(BaseModel):
    topic: Optional[str] = None
    website_url: Optional[str] = None
    brand_context: Optional[str] = None

class SocialPostsRequest(BaseModel):
    blog_slug: str
    include_linkedin: bool = True
    include_instagram: bool = True

class PodcastRequest(BaseModel):
    blog_slug: str

class WordPressSyncRequest(BaseModel):
    blog_slug: Optional[str] = None
    update_existing: bool = False

class BrandContextRequest(BaseModel):
    content: str

class SettingsRequest(BaseModel):
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_service_key: Optional[str] = None
    elevenlabs_api_key: Optional[str] = None
    wordpress_url: Optional[str] = None
    wordpress_username: Optional[str] = None
    wordpress_application_password: Optional[str] = None


# --------------- Dashboard page ---------------

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# --------------- Brand Context ---------------

@app.get("/api/brand-context")
async def get_brand_context():
    try:
        ctx_path = Path(__file__).parent / "brand_context.txt"
        if ctx_path.exists():
            return {"status": "success", "content": ctx_path.read_text(encoding="utf-8")}
        return {"status": "success", "content": ""}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.post("/api/brand-context")
async def save_brand_context(req: BrandContextRequest):
    try:
        ctx_path = Path(__file__).parent / "brand_context.txt"
        ctx_path.write_text(req.content, encoding="utf-8")
        return {"status": "success", "message": "Brand context saved"}
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# --------------- Blog generation ---------------

def _generate_blog_sync(topic: Optional[str], brand_context_override: Optional[str] = None):
    """Synchronous blog generation using existing seobot_ai pipeline."""
    from llm_client import generate_content, require_llm_config
    from seobot_ai import (
        load_brand_context, fetch_existing_blogs, build_prompt,
        extract_marked_json, extract_first_json, handle_tool_call,
    )

    require_llm_config()

    brand_context = brand_context_override or load_brand_context()
    existing_blogs = fetch_existing_blogs()
    existing_blogs_summary = "\n".join(
        [f"- {b['title']} ({b.get('category', 'N/A')})" for b in existing_blogs[:20]]
    )

    system_prompt = (
        "You are an expert SEO content strategist and blog writer. "
        "Create long-form, well-structured, and fact-checked blog content tailored to the brand."
    )
    prompt_text = build_prompt(system_prompt, brand_context, existing_blogs_summary, topic)

    g_text = generate_content(prompt_text)
    if not g_text:
        return {"status": "error", "message": "No content returned from LLM"}

    tool_calls = []
    start_marker = "<<<JSON_START>>>"
    end_marker = "<<<JSON_END>>>"
    idx = 0
    while True:
        s = g_text.find(start_marker, idx)
        if s == -1:
            break
        e = g_text.find(end_marker, s)
        if e == -1:
            break
        substring = g_text[s + len(start_marker):e].strip()
        try:
            parsed = json.loads(substring)
            if "tool" in parsed:
                tool_calls.append(parsed)
        except Exception:
            parsed2 = extract_first_json(substring)
            if parsed2 and "tool" in parsed2:
                tool_calls.append(parsed2)
        idx = e + len(end_marker)

    if not tool_calls:
        for line in g_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if (line.startswith("{") and line.endswith("}")) or (
                line.startswith("[") and line.endswith("]")
            ):
                try:
                    parsed = json.loads(line)
                    if "tool" in parsed:
                        tool_calls.append(parsed)
                except Exception:
                    pass
        if not tool_calls:
            parsed = extract_first_json(g_text)
            if parsed and "tool" in parsed:
                tool_calls.append(parsed)

    # Execute tool calls in order, but only create the CSV (no DB insert).
    for tc in tool_calls:
        tname = tc.get("tool")
        tinput = tc.get("input", {})
        res = handle_tool_call(tname, tinput)
        if tname == "blog_creator" and res.get("status") == "success":
            return {
                "status": "success",
                "message": "Blog generated successfully (CSV only, no Supabase insert).",
                "slug": res.get("slug"),
                "file_path": res.get("file_path"),
            }

    followup_prompt = (
        "You generated content above. Now, output ONLY a single JSON object wrapped between "
        "<<<JSON_START>>> and <<<JSON_END>>> markers, with this exact shape:\n"
        "<<<JSON_START>>>\n"
        '{"tool":"blog_creator","input": {"title":"...","slug":"...","meta_title":"...",'
        '"meta_description":"...","content":"<h1>...</h1>","excerpt":"...",'
        '"featured_image":"","category":"...","tags":["tag1","tag2"]}}\n'
        "<<<JSON_END>>>\nDo not output any other text."
    )
    g3_text = generate_content(followup_prompt + "\nPreviously generated content:\n" + (g_text or ""))
    obj = extract_marked_json(g3_text) or extract_first_json(g3_text)
    if not obj:
        return {"status": "error", "message": "Could not parse blog content from LLM response"}

    if obj.get("tool") == "blog_creator":
        creator_res = handle_tool_call("blog_creator", obj.get("input", {}))
        if creator_res.get("status") == "success":
            return {
                "status": "success",
                "message": "Blog generated successfully (CSV only, no Supabase insert).",
                "slug": creator_res.get("slug"),
                "file_path": creator_res.get("file_path"),
            }
        return {"status": "error", "message": creator_res.get("message")}

    return {"status": "error", "message": "LLM did not return a valid blog creation tool call"}


@app.post("/api/generate-blog")
async def generate_blog(req: BlogGenerateRequest):
    logger.info("POST /api/generate-blog  topic=%s  website=%s", req.topic, req.website_url)
    try:
        if req.brand_context:
            ctx_path = Path(__file__).parent / "brand_context.txt"
            ctx_path.write_text(req.brand_context, encoding="utf-8")
            logger.info("Brand context overridden and saved")

        result = await _run_in_thread(
            _generate_blog_sync, req.topic, req.brand_context
        )
        logger.info("Blog generation result: %s", result.get("status"))
        return result
    except Exception as e:
        logger.error("Blog generation failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# --------------- List blogs ---------------

def _list_blogs_from_csv() -> List[Dict[str, Any]]:
    """List all blogs from generated_blogs/*.csv files."""
    import csv as csv_module
    blogs = []
    blog_dir = Path(__file__).parent / "generated_blogs"
    if not blog_dir.exists():
        return []
    for f in sorted(blog_dir.glob("blog_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                reader = csv_module.DictReader(fp)
                row = next(reader, None)
                if not row:
                    continue
                # Parse tags from PostgreSQL array format {"a","b"} to list
                tags_raw = row.get("tags", "") or ""
                if tags_raw.strip().startswith("{"):
                    tags_str = tags_raw.strip("{}")
                    tags_list = [t.strip().strip('"') for t in tags_str.split(",") if t.strip()]
                else:
                    tags_list = []
                blogs.append({
                    "id": None,
                    "slug": row.get("slug", ""),
                    "title": row.get("title", ""),
                    "category": row.get("category", ""),
                    "excerpt": row.get("excerpt", ""),
                    "tags": tags_list,
                    "status": row.get("status", "published"),
                    "author": row.get("author", ""),
                    "read_time": row.get("read_time", "0"),
                    "published_at": row.get("published_at", ""),
                    "featured_image": row.get("featured_image", ""),
                    "source": "csv",
                })
        except Exception as e:
            logger.warning("Skip CSV %s: %s", f.name, e)
    return blogs


def _get_blog_from_csv(slug: str) -> Optional[Dict[str, Any]]:
    """Load a single blog from generated_blogs by slug (matches blog_{slug}_*.csv)."""
    import csv as csv_module
    blog_dir = Path(__file__).parent / "generated_blogs"
    if not blog_dir.exists():
        return None
    for f in blog_dir.glob(f"blog_{slug}_*.csv"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                reader = csv_module.DictReader(fp)
                row = next(reader, None)
                if not row:
                    continue
                tags_raw = row.get("tags", "") or ""
                if tags_raw.strip().startswith("{"):
                    tags_str = tags_raw.strip("{}")
                    tags_list = [t.strip().strip('"') for t in tags_str.split(",") if t.strip()]
                else:
                    tags_list = []
                return {
                    **row,
                    "tags": tags_list,
                    "source": "csv",
                }
        except Exception as e:
            logger.warning("Read CSV %s: %s", f.name, e)
    return None


@app.get("/api/blogs")
async def list_blogs():
    logger.info("GET /api/blogs")
    try:
        # 1) Blogs from Supabase (all statuses)
        supabase_blogs = []
        try:
            sb = _get_supabase()
            resp = sb.table("blog_posts").select(
                "id, slug, title, category, excerpt, tags, status, author, read_time, published_at, featured_image"
            ).order("published_at", desc=True).limit(50).execute()
            supabase_blogs = [{"source": "supabase", **b} for b in (resp.data or [])]
        except Exception as e:
            logger.warning("Supabase blogs: %s", e)

        # 2) Blogs from generated_blogs/*.csv (local only)
        csv_blogs = _list_blogs_from_csv()

        # 3) Merge: CSV slugs we already have from Supabase -> skip duplicate CSV so we don't show same blog twice
        supabase_slugs = {b["slug"] for b in supabase_blogs}
        csv_only = [b for b in csv_blogs if b["slug"] not in supabase_slugs]
        combined = supabase_blogs + csv_only
        # Sort by published_at desc (empty string last)
        combined.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        combined = combined[:80]

        logger.info("Returned %d blogs (%d Supabase + %d local CSV)", len(combined), len(supabase_blogs), len(csv_only))
        return {"status": "success", "blogs": combined}
    except Exception as e:
        logger.error("Failed to list blogs: %s", e)
        raise HTTPException(500, detail=str(e))


@app.get("/api/blogs/{slug}")
async def get_blog(slug: str):
    try:
        # 1) Try Supabase
        try:
            sb = _get_supabase()
            resp = sb.table("blog_posts").select("*").eq("slug", slug).execute()
            if resp.data:
                return {"status": "success", "blog": {**resp.data[0], "source": "supabase"}}
        except Exception:
            pass

        # 2) Try local CSV
        csv_blog = _get_blog_from_csv(slug)
        if csv_blog:
            return {"status": "success", "blog": csv_blog}

        raise HTTPException(404, detail="Blog not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# --------------- Social posts ---------------

def _generate_social_sync(blog_slug: str, include_linkedin: bool, include_instagram: bool):
    from social_posts_generator import generate_and_save_social_posts
    return generate_and_save_social_posts(blog_slug, include_linkedin, include_instagram)


@app.post("/api/social-posts")
async def generate_social_posts(req: SocialPostsRequest):
    logger.info("POST /api/social-posts  slug=%s  linkedin=%s  instagram=%s", req.blog_slug, req.include_linkedin, req.include_instagram)
    try:
        result = await _run_in_thread(
            _generate_social_sync, req.blog_slug, req.include_linkedin, req.include_instagram
        )
        logger.info("Social posts result: %s", result.get("status"))
        return result
    except Exception as e:
        logger.error("Social posts generation failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# --------------- Podcast ---------------

def _generate_podcast_sync(blog_slug: str):
    from podcast_generator import create_podcast_from_slug
    return create_podcast_from_slug(blog_slug)


@app.post("/api/podcast")
async def generate_podcast(req: PodcastRequest):
    logger.info("POST /api/podcast  slug=%s", req.blog_slug)
    try:
        result = await _run_in_thread(_generate_podcast_sync, req.blog_slug)
        logger.info("Podcast result: %s", result.get("status") if isinstance(result, dict) else "done")
        return result
    except Exception as e:
        logger.error("Podcast generation failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# --------------- WordPress sync ---------------

def _wp_sync_sync(blog_slug: Optional[str], update_existing: bool):
    from wordpress_sync import fetch_supabase_blogs, sync_blog_to_wordpress
    sb = _get_supabase()

    if blog_slug:
        resp = sb.table("blog_posts").select("*").eq("slug", blog_slug).execute()
        if not resp.data:
            return {"status": "error", "message": f"Blog '{blog_slug}' not found"}
        blog = resp.data[0]
    else:
        blogs = fetch_supabase_blogs(limit=1)
        if not blogs:
            return {"status": "error", "message": "No blogs found"}
        blog = blogs[0]

    result = sync_blog_to_wordpress(blog, update_existing=update_existing)
    return result


@app.post("/api/wordpress-sync")
async def wordpress_sync(req: WordPressSyncRequest):
    logger.info("POST /api/wordpress-sync  slug=%s  update=%s", req.blog_slug, req.update_existing)
    try:
        result = await _run_in_thread(_wp_sync_sync, req.blog_slug, req.update_existing)
        logger.info("WordPress sync result: %s", result.get("status"))
        return result
    except Exception as e:
        logger.error("WordPress sync failed: %s", e, exc_info=True)
        raise HTTPException(500, detail=str(e))


# --------------- Settings (read-only view of what's configured) ---------------

@app.get("/api/settings")
async def get_settings():
    return {
        "has_openrouter": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        "openrouter_model": os.getenv("OPENROUTER_MODEL", "arcee-ai/trinity-large-preview:free"),
        "has_gemini": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "gemini_model": os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash"),
        "has_supabase": bool(SUPABASE_URL and SUPABASE_SERVICE_KEY),
        "supabase_url": SUPABASE_URL[:30] + "..." if SUPABASE_URL else "",
        "has_elevenlabs": bool(os.getenv("ELEVENLABS_API_KEY", "").strip()),
        "has_wordpress": bool(os.getenv("WORDPRESS_URL", "").strip()),
        "wordpress_url": os.getenv("WORDPRESS_URL", ""),
    }


# --------------- Health check ---------------

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_includes=["*.py", "*.html"],
        reload_excludes=["__pycache__/*", "generated_*/*", "terminals/*", "venv/*"],
        log_level="info",
    )
