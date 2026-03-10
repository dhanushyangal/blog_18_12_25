#!/usr/bin/env python3
"""
seobot_ai_gemini.py

Gemini-only blog automation:
- Uses Google GenAI (Gemini) for text generation
- Uses Supabase for storage & DB inserts
- Robust JSON extraction (marked JSON + raw JSON scan)
- Produces SEO-optimized HTML blog and inserts into Supabase

Place in: Fundamentals_level_4/simple_blog_automation_script/
Required .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, and either OPENROUTER_API_KEY or GEMINI_API_KEY
Optional: OPENROUTER_MODEL (default arcee-ai/trinity-large-preview:free), GEMINI_MODEL (default models/gemini-2.5-flash)
"""

import os
import json
import csv
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from slugify import slugify

from llm_client import generate_content, require_llm_config

# Load environment
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# Validate
if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing required environment variables. Check .env: SUPABASE_URL, SUPABASE_SERVICE_KEY")
require_llm_config()

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
    {"name": "blog_creator", "description": "Create a blog CSV"},
    {"name": "blog_inserter", "description": "Insert blog CSV into Supabase"}
]

def handle_tool_call(tool_name: str, tool_args: Dict) -> Dict:
    if tool_name == "blog_creator":
        return blog_creator(**tool_args)
    elif tool_name == "blog_inserter":
        return blog_inserter(**tool_args)
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
              "- At the end, output a JSON object (on its own line) with shape: {\"tool\":\"blog_creator\", \"input\": { ... }} containing fields: title, slug, meta_title, meta_description, content, excerpt, featured_image (leave empty), category, tags (array).\n"
              "- Keep the HTML valid and minimal (no markdown).\n")
    instr += ("IMPORTANT for parsing: When emitting JSON for tools, please wrap the single JSON object between markers EXACTLY like:\n"
              "<<<JSON_START>>>\n"
              '{"tool":"blog_creator","input": {...} }\n'
              "<<<JSON_END>>>\n"
              "and output nothing else on those marker lines.\n")
    instr += ("SEO instructions: Use an engaging H1, include the main keyword in the first 100 words, craft a concise meta description (<=160 chars), use H2/H3s, and suggest 6-12 tags.\n")
    return instr

# -------------------- Main flow --------------------

def main():
    import sys
    print("🚀 Starting Gemini-only AI Blog Generator...")
    
    # Allow topic to be passed as command-line argument
    if len(sys.argv) > 1:
        user_topic = sys.argv[1].strip() or None
        print(f"\nUsing topic from command line: {user_topic if user_topic else 'Auto-generate'}")
    else:
        try:
            user_topic = input("\nEnter article topic (or press ENTER to auto-generate):\n> ").strip() or None
        except EOFError:
            # Handle non-interactive environments
            print("\nNo topic provided. Auto-generating topic...")
            user_topic = None

    brand_context = load_brand_context()
    existing_blogs = fetch_existing_blogs()
    existing_blogs_summary = '\n'.join([f"- {b['title']} ({b.get('category','N/A')})" for b in existing_blogs[:20]])

    system_prompt = "You are an expert SEO content strategist and blog writer for reconstructyourmind.com. Create long-form, well-structured, and fact-checked blog content tailored to the brand."

    prompt_text = build_prompt(system_prompt, brand_context, existing_blogs_summary, user_topic)

    print("\n🔁 Sending prompt to LLM (this may take a bit)...")
    try:
        g_text = generate_content(prompt_text)
        if not g_text:
            print("No content returned from LLM.")
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
            print(f"\n🔧 LLM requested tool: {tname}")
            res = handle_tool_call(tname, tinput)
            print("   Result:", res.get('message'))
            # If blog_creator succeeded, insert into database
            if tname == 'blog_creator' and res.get('status') == 'success':
                insert_res = handle_tool_call('blog_inserter', {'csv_file_path': res.get('file_path')})
                print('   blog_inserter:', insert_res.get('message'))
                if insert_res.get('status') == 'success':
                    print('\n✅ Blog published at:', insert_res.get('url'))
                    return 0

        # If no tool_calls or no final insert yet, ask LLM to emit blog_creator JSON for the content it generated
        followup_prompt = (
            "You generated content above. Now, output ONLY a single JSON object wrapped between <<<JSON_START>>> and <<<JSON_END>>> markers, "
            "with this exact shape:\n"
            "<<<JSON_START>>>\n"
            '{"tool":"blog_creator","input": {"title":"...","slug":"...","meta_title":"...","meta_description":"...","content":"<h1>...</h1>","excerpt":"...","featured_image":"","category":"...","tags":["tag1","tag2"]}}\n'
            "<<<JSON_END>>>\n"
            "Do not output any other text. The JSON must be valid."
        )
        g3_text = generate_content(followup_prompt + "\nPreviously generated content:\n" + (g_text or ""))
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
        print('\n❌ Error while calling LLM:', e)
        return 1

if __name__ == '__main__':
    exit(main())
