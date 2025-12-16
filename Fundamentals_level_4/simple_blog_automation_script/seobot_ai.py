#!/usr/bin/env python3
"""
seobot_ai_gemini.py

Gemini-only blog automation:
- Uses Google GenAI (Gemini) for text generation
- Uses Supabase for storage & DB inserts
- Falls back to placeholder images when Imagen access is unavailable
- Robust JSON extraction (marked JSON + raw JSON scan)
- Produces SEO-optimized HTML blog and inserts into Supabase

Place in: Fundamentals_level_4/simple_blog_automation_script/
Required .env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, GEMINI_API_KEY, BUCKET_NAME
Optional .env vars: GEMINI_MODEL (defaults to models/gemini-2.5-flash), IMAGEN_MODEL
"""

import os
import json
import csv
import mimetypes
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from slugify import slugify
from google import genai
from PIL import Image, ImageDraw

# Load environment
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# Validate
if not all([GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing required environment variables. Check .env: GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY")

# Clients
client_genai = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# -------------------- Helpers --------------------

def extract_first_json(text: str):
    """
    Find and return the first JSON object or array inside text.
    Returns parsed object or None.
    """
    if not text:
        return None
    decoder = json.JSONDecoder()
    idx = 0
    L = len(text)
    while idx < L:
        # find next { or [
        next_brace = min(
            (text.find('{', idx) if text.find('{', idx) != -1 else L),
            (text.find('[', idx) if text.find('[', idx) != -1 else L)
        )
        if next_brace >= L:
            break
        try:
            obj, end = decoder.raw_decode(text[next_brace:])
            return obj
        except json.JSONDecodeError:
            idx = next_brace + 1
            continue
    return None

def extract_marked_json(text: str, start_marker: str = "<<<JSON_START>>>", end_marker: str = "<<<JSON_END>>>"):
    """
    Extract JSON wrapped between explicit markers.
    Returns parsed object or None.
    """
    if not text:
        return None
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start != -1 and end != -1 and end > start:
        substring = text[start + len(start_marker):end].strip()
        try:
            return json.loads(substring)
        except Exception as e:
            print("DEBUG: Marked JSON parse error:", e)
            # print first chunk for debugging (no secrets)
            print("DEBUG: Marked substring (truncated):", substring[:1000])
            return None
    return None

# -------------------- Content helpers --------------------

def load_brand_context() -> str:
    try:
        with open('brand_context.txt', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "Reconstruct is a platform to build an everyday mental fitness routine."

def fetch_existing_blogs(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        resp = supabase.table('blog_posts').select('title, slug, category, excerpt').eq('status', 'published').limit(limit).execute()
        return resp.data if resp.data else []
    except Exception as e:
        print("Warning: could not fetch existing blogs:", e)
        return []

def calculate_read_time(content: str) -> int:
    words_per_minute = 200
    wc = len(content.split())
    return max(1, round(wc / words_per_minute))

# -------------------- Image helpers --------------------

def _make_placeholder_image(prompt_text: str, local_filename: str) -> str:
    os.makedirs(os.path.dirname(local_filename), exist_ok=True)
    w, h = 1920, 1080
    img = Image.new('RGB', (w, h), color=(245, 245, 245))
    draw = ImageDraw.Draw(img)
    title = "Placeholder Image"
    draw.text((60, 120), title, fill=(40, 40, 40))
    prompt_preview = (prompt_text or '')[:400]
    draw.text((60, 200), prompt_preview, fill=(80, 80, 80))
    img.save(local_filename, 'JPEG', quality=85, optimize=True)
    return local_filename

def image_generator(prompt: str) -> Dict[str, Any]:
    """
    Generate image via Imagen if possible; otherwise produce local placeholder.
    Returns dict with keys: status, message, local_path
    """
    try:
        model = os.getenv('IMAGEN_MODEL', 'models/imagen-4.0-ultra-generate-001')
        try:
            result = client_genai.models.generate_images(
                model=model,
                prompt=prompt,
                config=dict(number_of_images=1, output_mime_type='image/jpeg', aspect_ratio='16:9', image_size='1K')
            )
            if getattr(result, "generated_images", None):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                local_filename = f"generated_images/blog_header_{timestamp}.jpg"
                os.makedirs('generated_images', exist_ok=True)
                img_obj = result.generated_images[0]
                # Attempt to save via attribute or base64 fallback
                try:
                    img_obj.image.save(local_filename)
                except Exception:
                    if hasattr(img_obj, 'b64_json'):
                        import base64
                        data = base64.b64decode(img_obj.b64_json)
                        with open(local_filename, 'wb') as f:
                            f.write(data)
                    else:
                        raise
                return {"status": "success", "message": "Image generated", "local_path": local_filename}
        except Exception as e:
            # Imagen likely unavailable (billing/access) — fallback
            print("Imagen generation error (falling back to placeholder):", e)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            local_filename = f"generated_images/placeholder_{timestamp}.jpg"
            _make_placeholder_image(prompt, local_filename)
            return {"status": "success", "message": "Imagen unavailable — placeholder created", "local_path": local_filename}

        # If SDK returns but no images, create placeholder
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        local_filename = f"generated_images/placeholder_{timestamp}.jpg"
        _make_placeholder_image(prompt, local_filename)
        return {"status": "success", "message": "No image generated — placeholder created", "local_path": local_filename}

    except Exception as e:
        return {"status": "error", "message": f"Failed to generate image: {e}"}

def image_uploader(local_path: str, file_name: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not BUCKET_NAME:
            return {"status": "error", "message": "BUCKET_NAME not configured in .env"}
        with open(local_path, 'rb') as f:
            file_data = f.read()
        _, ext = os.path.splitext(local_path)
        if not file_name:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_name = f"blog_header_{timestamp}{ext}"
        bucket = supabase.storage.from_(BUCKET_NAME)
        bucket.upload(path=f"blog-images/{file_name}", file=file_data, file_options={"content-type": mimetypes.guess_type(local_path)[0] or 'image/jpeg'})
        public_url = bucket.get_public_url(f"blog-images/{file_name}")
        return {"status": "success", "message": "Image uploaded", "public_url": public_url, "file_path": f"blog-images/{file_name}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to upload image: {e}"}

# -------------------- Blog creation & insertion --------------------

def generate_schema_markup(title: str, description: str, author: str, published_date: str, image_url: str, faq_items: List[Dict[str, str]] = None) -> str:
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "author": {"@type": "Person", "name": author, "url": "https://reconstructyourmind.com"},
        "datePublished": published_date,
        "dateModified": published_date,
        "image": image_url,
        "publisher": {"@type": "Organization", "name": "Reconstruct", "logo": {"@type": "ImageObject", "url": "https://reconstructyourmind.com/logo.png"}},
        "mainEntityOfPage": {"@type": "WebPage", "@id": f"https://reconstructyourmind.com/blog/{slugify(title)[:200]}"}
    }
    if faq_items:
        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": item["question"], "acceptedAnswer": {"@type": "Answer", "text": item["answer"]}} for item in faq_items]
        }
        return f'<script type="application/ld+json">{json.dumps(schema)}</script>\n<script type="application/ld+json">{json.dumps(faq_schema)}</script>'
    return f'<script type="application/ld+json">{json.dumps(schema)}</script>'

#def blog_creator(title: str, slug: str, meta_title: str, meta_description: str, content: str, excerpt: str, featured_image: str, category: str, tags: List[str], author: str = "Reconstruct Team") -> Dict[str, Any]:
    try:
        slug = slugify(slug or title)[:255]
        schema_markup = generate_schema_markup(title, meta_description or excerpt, author, datetime.now(timezone.utc).isoformat(), featured_image, None)
        enhanced_content = schema_markup + "\n" + content
        read_time = calculate_read_time(content)
        timestamp = datetime.now(timezone.utc).isoformat()
        blog_data = {
            'slug': slug,
            'title': title[:255],
            'meta_title': (meta_title or title)[:100],
            'meta_description': (meta_description or excerpt)[:255],
            'content': enhanced_content,
            'excerpt': excerpt,
            'featured_image': featured_image[:500] if featured_image else '',
            'category': category[:100],
            'tags': '{' + ','.join([f'"{tag}"' for tag in tags]) + '}',
            'author': author[:100],
            'status': 'published',
            'featured': 'false',
            'read_time': str(read_time),
            'view_count': '0',
            'published_at': timestamp,
            'updated_at': timestamp,
            'created_at': timestamp
        }
        csv_filename = f"blog_{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = os.path.join('generated_blogs', csv_filename)
        os.makedirs('generated_blogs', exist_ok=True)
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=blog_data.keys())
            writer.writeheader()
            writer.writerow(blog_data)
        return {"status": "success", "message": f"Blog created successfully: {title}", "file_path": csv_path, "slug": slug}
    except Exception as e:
        return {"status": "error", "message": f"Failed to create blog: {e}"}
def _coerce_to_str(x):
    """Safe coercion to string for CSV/HTML storage."""
    if x is None:
        return ""
    # If it's already a string, return as-is
    if isinstance(x, str):
        return x
    # If it's a list or tuple, join with newlines (preserve some structure)
    if isinstance(x, (list, tuple)):
        try:
            return "\n".join(str(i) for i in x)
        except Exception:
            return json.dumps(x, ensure_ascii=False)
    # If it's a dict, dump to JSON (compact)
    if isinstance(x, dict):
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return str(x)
    # Fallback
    try:
        return str(x)
    except Exception:
        return ""

def _coerce_tags(tags):
    """Return a list of tags from many possible input shapes."""
    if tags is None:
        return []
    # Already a list/tuple
    if isinstance(tags, (list, tuple)):
        return [str(t).strip() for t in tags if str(t).strip()]
    # If it's a string, maybe JSON or comma-separated
    if isinstance(tags, str):
        txt = tags.strip()
        # try JSON
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, (list, tuple)):
                return [str(t).strip() for t in parsed if str(t).strip()]
        except Exception:
            pass
        # fallback: comma-split
        return [t.strip() for t in txt.split(",") if t.strip()]
    # If it's a dict (rare), take values or keys
    if isinstance(tags, dict):
        vals = list(tags.values())
        if vals:
            return [str(t).strip() for t in vals if str(t).strip()]
        return [str(k).strip() for k in tags.keys() if str(k).strip()]
    # Anything else: coerce to string and split
    return [t.strip() for t in _coerce_to_str(tags).split(",") if t.strip()]

def blog_creator(title: str, slug: str, meta_title: str, meta_description: str,
                 content: str, excerpt: str, featured_image: str, category: str,
                 tags: List[str], author: str = "Reconstruct Team") -> Dict[str, Any]:
    """
    Hardened blog_creator: sanitizes inputs and writes CSV.
    Returns status dict like before.
    """
    try:
        # Basic coercions
        try:
            title_s = _coerce_to_str(title).strip()
            slug_s = _coerce_to_str(slug).strip() or slugify(title_s)[:255]
            meta_title_s = _coerce_to_str(meta_title).strip() or title_s[:100]
            meta_description_s = _coerce_to_str(meta_description).strip() or _coerce_to_str(excerpt)[:255]
            content_s = _coerce_to_str(content)
            excerpt_s = _coerce_to_str(excerpt)
            featured_image_s = _coerce_to_str(featured_image)
            category_s = _coerce_to_str(category)
            author_s = _coerce_to_str(author)[:100]
        except Exception as e:
            # If any coercion fails, debug and fallback
            print("DEBUG: coercion error in blog_creator:", e)
            title_s = _coerce_to_str(title)
            slug_s = slugify(title_s)[:255]
            meta_title_s = _coerce_to_str(meta_title)
            meta_description_s = _coerce_to_str(meta_description)
            content_s = _coerce_to_str(content)
            excerpt_s = _coerce_to_str(excerpt)
            featured_image_s = _coerce_to_str(featured_image)
            category_s = _coerce_to_str(category)
            author_s = _coerce_to_str(author)

        # Normalize tags
        tags_list = _coerce_tags(tags)

        # Generate schema + enhanced content
        schema_markup = generate_schema_markup(title_s, meta_description_s or excerpt_s, author_s, datetime.now(timezone.utc).isoformat(), featured_image_s, None)
        enhanced_content = schema_markup + "\n" + content_s

        read_time = calculate_read_time(content_s)
        timestamp = datetime.now(timezone.utc).isoformat()

        # Compose tags into PostgreSQL array literal format expected by your earlier code
        tags_field = "{" + ",".join([f'"{t}"' for t in tags_list]) + "}"

        blog_data = {
            'slug': slug_s[:255],
            'title': title_s[:255],
            'meta_title': meta_title_s[:100],
            'meta_description': meta_description_s[:255],
            'content': enhanced_content,
            'excerpt': excerpt_s,
            'featured_image': featured_image_s[:500] if featured_image_s else '',
            'category': category_s[:100],
            'tags': tags_field,
            'author': author_s[:100],
            'status': 'published',
            'featured': 'false',
            'read_time': str(read_time),
            'view_count': '0',
            'published_at': timestamp,
            'updated_at': timestamp,
            'created_at': timestamp
        }

        # Write CSV safely: ensure csv fieldnames are strings in stable order
        fieldnames = list(blog_data.keys())
        csv_filename = f"blog_{slug_s}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        csv_path = os.path.join('generated_blogs', csv_filename)
        os.makedirs('generated_blogs', exist_ok=True)
        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(blog_data)

        return {"status": "success", "message": f"Blog created successfully: {title_s}", "file_path": csv_path, "slug": slug_s}
    except Exception as e:
        # Provide helpful debug (no secrets)
        print("DEBUG: blog_creator caught exception:", repr(e))
        # Print types of incoming values for diagnosis
        try:
            print("DEBUG types:", {k: type(v).__name__ for k, v in {
                'title': title, 'slug': slug, 'meta_title': meta_title, 'meta_description': meta_description,
                'content': content, 'excerpt': excerpt, 'featured_image': featured_image, 'category': category,
                'tags': tags, 'author': author
            }.items()})
        except Exception:
            pass
        return {"status": "error", "message": f"Failed to create blog: {e}"}

def blog_inserter(csv_file_path: str = None, file_path: str = None) -> Dict[str, Any]:
    try:
        csv_path = csv_file_path or file_path
        if not csv_path:
            return {"status": "error", "message": "No csv file path provided to blog_inserter"}
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            blog_data = next(reader)
        existing = supabase.table('blog_posts').select('id').eq('slug', blog_data['slug']).execute()
        if existing.data:
            return {"status": "error", "message": f"Blog with slug '{blog_data['slug']}' already exists"}
        tags_str = blog_data['tags'].strip('{}')
        tags_list = [tag.strip().strip('"') for tag in tags_str.split(',') if tag.strip()]
        blog_post = {
            'slug': blog_data['slug'],
            'title': blog_data['title'],
            'meta_title': blog_data['meta_title'],
            'meta_description': blog_data['meta_description'],
            'content': blog_data['content'],
            'excerpt': blog_data['excerpt'],
            'featured_image': blog_data['featured_image'],
            'category': blog_data['category'],
            'tags': tags_list,
            'author': blog_data['author'],
            'status': blog_data['status'],
            'featured': blog_data['featured'] == 'true',
            'read_time': int(blog_data['read_time']),
            'view_count': int(blog_data['view_count']),
            'published_at': blog_data['published_at'],
            'updated_at': blog_data['updated_at'],
            'created_at': blog_data['created_at']
        }
        resp = supabase.table('blog_posts').insert(blog_post).execute()
        if resp.data:
            return {"status": "success", "message": "Blog inserted successfully", "url": f"https://reconstructyourmind.com/blog/{blog_data['slug']}"}
        else:
            return {"status": "error", "message": "Failed to insert blog: No data returned"}
    except Exception as e:
        return {"status": "error", "message": f"Error inserting blog: {e}"}

# -------------------- Tool dispatcher --------------------

TOOLS = [
    {"name": "image_generator", "description": "Generate an image or placeholder"},
    {"name": "image_uploader", "description": "Upload local image to Supabase bucket"},
    {"name": "blog_creator", "description": "Create a blog CSV"},
    {"name": "blog_inserter", "description": "Insert blog CSV into Supabase"}
]

def handle_tool_call(tool_name: str, tool_args: Dict) -> Dict:
    if tool_name == "blog_creator":
        return blog_creator(**tool_args)
    elif tool_name == "blog_inserter":
        return blog_inserter(**tool_args)
    elif tool_name == "image_generator":
        return image_generator(prompt=tool_args.get("prompt", ""))
    elif tool_name == "image_uploader":
        return image_uploader(**tool_args)
    else:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}

# -------------------- Prompt builder --------------------

def build_prompt(system_prompt: str, brand_context: str, existing_blogs_summary: str, user_topic: Optional[str]) -> str:
    instr = system_prompt + "\n\n"
    instr += "BRAND_CONTEXT:\n" + brand_context[:2000] + "\n\n"
    instr += "EXISTING_BLOGS_SUMMARY:\n" + existing_blogs_summary[:2000] + "\n\n"
    if user_topic:
        instr += f"FOCUS TOPIC: {user_topic}\n\n"
    instr += ("Your task: produce a fully-formed, SEO-optimized HTML blog post (2000-3000 words) including:\n"
              "- <h1> title, <meta> title and description, structured headings, FAQ (5+ Q&As), References section with URLs.\n"
              "- Use inline citations like [1], [2] where facts are stated.\n"
              "- At the end, output a JSON object (on its own line) with shape: {\"tool\":\"blog_creator\", \"input\": { ... }} containing fields: title, slug, meta_title, meta_description, content, excerpt, featured_image, category, tags (array).\n"
              "- If you want an image, output a tool call JSON (on its own line): {\"tool\":\"image_generator\", \"input\": {\"prompt\":\"...\"}} BEFORE the blog_creator JSON.\n"
              "- Keep the HTML valid and minimal (no markdown).\n")
    instr += ("IMPORTANT for parsing: When emitting JSON for tools, please wrap the single JSON object between markers EXACTLY like:\n"
              "<<<JSON_START>>>\n"
              '{"tool":"blog_creator","input": {...} }\n'
              "<<<JSON_END>>>\n"
              "and output nothing else on those marker lines. Do the same for image_generator calls.\n")
    instr += ("SEO instructions: Use an engaging H1, include the main keyword in the first 100 words, craft a concise meta description (<=160 chars), use H2/H3s, add alt text for the featured image, and suggest 6-12 tags.\n")
    return instr

# -------------------- Main flow --------------------

def main():
    print("🚀 Starting Gemini-only AI Blog Generator...")
    user_topic = input("\nEnter article topic (or press ENTER to auto-generate):\n> ").strip() or None

    brand_context = load_brand_context()
    existing_blogs = fetch_existing_blogs()
    existing_blogs_summary = '\n'.join([f"- {b['title']} ({b.get('category','N/A')})" for b in existing_blogs[:20]])

    system_prompt = "You are an expert SEO content strategist and blog writer for reconstructyourmind.com. Create long-form, well-structured, and fact-checked blog content tailored to the brand."

    prompt_text = build_prompt(system_prompt, brand_context, existing_blogs_summary, user_topic)

    print("\n🔁 Sending prompt to Gemini (this may take a bit)...")
    try:
        resp = client_genai.models.generate_content(model=GEMINI_MODEL, contents=prompt_text)
        g_text = getattr(resp, 'text', None) or (resp.output[0].content if getattr(resp, 'output', None) else None)
        if not g_text:
            print("No content returned from Gemini.")
            return 1

        # Look for JSON tool-call objects in the response (either marked or raw)
        # Process them in order of appearance using helpers
        tool_calls = []
        # First, try to extract marked JSON blocks (multiple)
        # naive scan for markers
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
                if 'tool' in parsed:
                    tool_calls.append(parsed)
            except Exception:
                # fallback: try raw decode on substring
                parsed2 = extract_first_json(substring)
                if parsed2 and 'tool' in parsed2:
                    tool_calls.append(parsed2)
            idx = e + len(end_marker)

        # If no marked tool calls found, try to extract raw JSON objects from whole text
        if not tool_calls:
            # split lines and try raw decode per line
            for line in g_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if (line.startswith("{") and line.endswith("}")) or (line.startswith("[") and line.endswith("]")):
                    try:
                        parsed = json.loads(line)
                        if 'tool' in parsed:
                            tool_calls.append(parsed)
                            continue
                    except Exception:
                        pass
            # final fallback: raw scan
            if not tool_calls:
                parsed = extract_first_json(g_text)
                if parsed and 'tool' in parsed:
                    tool_calls.append(parsed)

        # Execute tool calls in order
        for tc in tool_calls:
            tname = tc.get('tool')
            tinput = tc.get('input', {})
            print(f"\n🔧 Gemini requested tool: {tname}")
            res = handle_tool_call(tname, tinput)
            print("   Result:", res.get('message'))
            # If image generated, upload and then request blog_creator JSON with the image URL
            if tname == 'image_generator' and res.get('status') == 'success':
                up = handle_tool_call('image_uploader', {'local_path': res.get('local_path')})
                print('   Upload result:', up.get('message'))
                if up.get('status') == 'success':
                    image_url = up.get('public_url')
                    # Ask Gemini to produce blog_creator JSON referencing this image (wrapped in markers)
                    followup = (
                        "<<<JSON_START>>>\n"
                        '{"tool":"blog_creator","input": {'
                        f'"title": "", "slug": "", "meta_title": "", "meta_description": "", "content": "", "excerpt": "", "featured_image": "{image_url}", "category": "", "tags": []'
                        '}}\n'
                        "<<<JSON_END>>>\n"
                        "Please only output the JSON between markers above to instruct the program to create the blog. "
                    )
                    resp2 = client_genai.models.generate_content(model=GEMINI_MODEL, contents=followup + "\nPreviously generated content:\n" + g_text)
                    g2_text = getattr(resp2, 'text', None) or (resp2.output[0].content if getattr(resp2, 'output', None) else None)
                    parsed_obj = extract_marked_json(g2_text) or extract_first_json(g2_text)
                    if not parsed_obj:
                        print("DEBUG: Could not find JSON in Gemini follow-up. Raw follow-up preview:\n", (g2_text or "")[:2000])
                        return 1
                    if parsed_obj.get('tool') == 'blog_creator':
                        creator_res = handle_tool_call('blog_creator', parsed_obj.get('input', {}))
                        print('   blog_creator:', creator_res.get('message'))
                        if creator_res.get('status') == 'success':
                            insert_res = handle_tool_call('blog_inserter', {'csv_file_path': creator_res.get('file_path')})
                            print('   blog_inserter:', insert_res.get('message'))
                            if insert_res.get('status') == 'success':
                                print('\n✅ Blog published at:', insert_res.get('url'))
                                return 0

        # If no tool_calls or no final insert yet, ask Gemini to emit blog_creator JSON for the content it generated
        followup_prompt = (
            "You generated content above. Now, output ONLY a single JSON object wrapped between <<<JSON_START>>> and <<<JSON_END>>> markers, "
            "with this exact shape:\n"
            "<<<JSON_START>>>\n"
            '{"tool":"blog_creator","input": {"title":"...","slug":"...","meta_title":"...","meta_description":"...","content":"<h1>...</h1>","excerpt":"...","featured_image":"","category":"...","tags":["tag1","tag2"]}}\n'
            "<<<JSON_END>>>\n"
            "Do not output any other text. The JSON must be valid."
        )
        resp3 = client_genai.models.generate_content(model=GEMINI_MODEL, contents=followup_prompt + "\nPreviously generated content:\n" + (g_text or ""))
        g3_text = getattr(resp3, 'text', None) or (resp3.output[0].content if getattr(resp3, 'output', None) else None)
        obj = extract_marked_json(g3_text) or extract_first_json(g3_text)
        if not obj:
            print("DEBUG: Could not find final blog_creator JSON. Raw follow-up preview:\n", (g3_text or "")[:2000])
            print("\n⚠️ Blog creation process completed but blog was not inserted")
            return 1
        if obj.get('tool') == 'blog_creator':
            creator_res = handle_tool_call('blog_creator', obj.get('input', {}))
            print('   blog_creator:', creator_res.get('message'))
            if creator_res.get('status') == 'success':
                insert_res = handle_tool_call('blog_inserter', {'csv_file_path': creator_res.get('file_path')})
                print('   blog_inserter:', insert_res.get('message'))
                if insert_res.get('status') == 'success':
                    print('\n✅ Blog published at:', insert_res.get('url'))
                    return 0

        print('\n⚠️ Blog creation process completed but blog was not inserted')
        return 1

    except Exception as e:
        print('\n❌ Error while calling Gemini:', e)
        return 1

if __name__ == '__main__':
    exit(main())
