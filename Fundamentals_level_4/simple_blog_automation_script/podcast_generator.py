#!/usr/bin/env python3
"""
podcast_generator.py

Podcast generation from blog posts:
- Reads blog posts from CSV files or Supabase
- Uses Gemini to generate podcast scripts
- Provides NotebookLM web interface instructions
- Stores podcast metadata and can update blog posts

Place in: Fundamentals_level_4/simple_blog_automation_script/
Required .env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, GEMINI_API_KEY
"""

import os
import json
import csv
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from slugify import slugify
from google import genai
from bs4 import BeautifulSoup

# Load environment
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")

# Validate
if not all([GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing required environment variables. Check .env: GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY")

# Clients
client_genai = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# -------------------- Helpers --------------------

def extract_text_from_html(html_content: str) -> str:
    """Extract plain text from HTML content."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text()
    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    return text

def load_brand_context() -> str:
    """Load brand context from file."""
    try:
        with open('brand_context.txt', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "Reconstruct is a platform to build an everyday mental fitness routine."

def read_blog_from_csv(csv_path: str) -> Optional[Dict[str, Any]]:
    """Read blog post data from CSV file."""
    try:
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            blog_data = next(reader)
            return blog_data
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return None

def fetch_blog_from_supabase(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch blog post from Supabase by slug."""
    try:
        resp = supabase.table('blog_posts').select('*').eq('slug', slug).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0]
        return None
    except Exception as e:
        print(f"Error fetching from Supabase: {e}")
        return None

def list_available_blogs() -> List[Dict[str, Any]]:
    """List all available blog CSV files."""
    blogs = []
    blog_dir = os.path.join('..', '..', 'generated_blogs')
    if not os.path.exists(blog_dir):
        blog_dir = 'generated_blogs'
    
    if os.path.exists(blog_dir):
        for filename in os.listdir(blog_dir):
            if filename.endswith('.csv') and filename.startswith('blog_'):
                blogs.append({
                    'filename': filename,
                    'path': os.path.join(blog_dir, filename),
                    'slug': filename.replace('blog_', '').replace('.csv', '').rsplit('_', 2)[0]
                })
    return blogs

# -------------------- Podcast Script Generation --------------------

def generate_podcast_script(blog_title: str, blog_content: str, blog_excerpt: str, 
                            brand_context: str, duration_minutes: int = 15) -> Dict[str, Any]:
    """
    Generate a podcast script from blog content using Gemini.
    
    Returns:
        Dict with 'script', 'segments', 'intro', 'outro', 'key_points'
    """
    # Extract plain text from HTML
    plain_text = extract_text_from_html(blog_content)
    
    # Limit content length for prompt (keep it manageable)
    content_preview = plain_text[:5000] if len(plain_text) > 5000 else plain_text
    
    prompt = f"""You are a professional podcast script writer. Create an engaging podcast script based on this blog post.

BLOG TITLE: {blog_title}

BLOG EXCERPT: {blog_excerpt[:500]}

BLOG CONTENT (excerpt):
{content_preview}

BRAND CONTEXT:
{brand_context[:1000]}

Create a podcast script that:
1. Is conversational and engaging (like a host explaining to a friend)
2. Duration: approximately {duration_minutes} minutes (aim for {duration_minutes * 150} words)
3. Includes:
   - An engaging intro (30-60 seconds)
   - Main content broken into 3-5 segments with natural transitions
   - Key takeaways and actionable tips
   - A memorable outro with call-to-action

Format the response as JSON with this structure:
{{
    "intro": "Opening lines (30-60 seconds)",
    "segments": [
        {{
            "title": "Segment title",
            "content": "Full script for this segment",
            "duration_estimate": "X minutes"
        }}
    ],
    "key_points": ["Point 1", "Point 2", "Point 3"],
    "outro": "Closing lines with call-to-action",
    "total_duration_estimate": "{duration_minutes} minutes",
    "show_notes": "Brief description for podcast platforms"
}}

Make it natural, conversational, and easy to read aloud. Use the brand voice from the context provided.
"""

    try:
        resp = client_genai.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        g_text = getattr(resp, 'text', None) or (resp.output[0].content if getattr(resp, 'output', None) else None)
        
        if not g_text:
            return {"status": "error", "message": "No content returned from Gemini"}
        
        # Try to extract JSON from response
        json_match = re.search(r'\{.*\}', g_text, re.DOTALL)
        if json_match:
            try:
                script_data = json.loads(json_match.group())
                script_data['status'] = 'success'
                script_data['raw_response'] = g_text
                return script_data
            except json.JSONDecodeError:
                pass
        
        # Fallback: return raw text as script
        return {
            "status": "success",
            "intro": g_text[:500],
            "segments": [{"title": "Main Content", "content": g_text, "duration_estimate": f"{duration_minutes} minutes"}],
            "key_points": [],
            "outro": "Thanks for listening!",
            "total_duration_estimate": f"{duration_minutes} minutes",
            "show_notes": blog_excerpt[:200],
            "raw_response": g_text
        }
    except Exception as e:
        return {"status": "error", "message": f"Error generating script: {e}"}

# -------------------- Podcast File Management --------------------

def save_comprehensive_notebooklm_file(blog_slug: str, script_data: Dict[str, Any], 
                                       blog_title: str, blog_excerpt: str,
                                       blog_content: str, brand_context: str) -> str:
    """
    Save a single comprehensive file with everything needed for NotebookLM.
    This file contains blog content, brand context, generated script, and instructions.
    """
    os.makedirs('generated_podcasts', exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"notebooklm_{blog_slug}_{timestamp}.txt"
    filepath = os.path.join('generated_podcasts', filename)
    
    # Extract plain text from HTML blog content
    plain_blog_text = extract_text_from_html(blog_content)
    
    # Format comprehensive file for NotebookLM
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("PODCAST GENERATION FILE FOR NOTEBOOKLM\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("INSTRUCTIONS FOR NOTEBOOKLM:\n")
        f.write("-" * 80 + "\n")
        f.write("1. Upload this entire file to NotebookLM (https://notebooklm.google.com)\n")
        f.write("2. Once uploaded, ask NotebookLM: 'Create a podcast script based on this blog post'\n")
        f.write("3. Or ask: 'Generate a conversational podcast episode from the blog content below'\n")
        f.write("4. NotebookLM will use all the information in this file to create the podcast\n")
        f.write("5. Refine the output as needed with follow-up questions\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("BLOG INFORMATION\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Title: {blog_title}\n")
        f.write(f"Slug: {blog_slug}\n")
        f.write(f"Excerpt: {blog_excerpt}\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("BRAND CONTEXT\n")
        f.write("=" * 80 + "\n\n")
        f.write(brand_context)
        f.write("\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("ORIGINAL BLOG CONTENT\n")
        f.write("=" * 80 + "\n\n")
        f.write(plain_blog_text)
        f.write("\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("GENERATED PODCAST SCRIPT (DRAFT)\n")
        f.write("=" * 80 + "\n\n")
        f.write("This is an AI-generated draft. Use NotebookLM to refine and enhance it.\n\n")
        f.write(f"Estimated Duration: {script_data.get('total_duration_estimate', 'N/A')}\n\n")
        
        # Intro
        f.write("INTRO:\n")
        f.write("-" * 80 + "\n")
        f.write(script_data.get('intro', '') + "\n\n")
        
        # Segments
        segments = script_data.get('segments', [])
        for i, segment in enumerate(segments, 1):
            f.write(f"\nSEGMENT {i}: {segment.get('title', f'Segment {i}')}\n")
            f.write("-" * 80 + "\n")
            f.write(f"Duration: {segment.get('duration_estimate', 'N/A')}\n\n")
            f.write(segment.get('content', '') + "\n\n")
        
        # Key Points
        key_points = script_data.get('key_points', [])
        if key_points:
            f.write("\nKEY TAKEAWAYS:\n")
            f.write("-" * 80 + "\n")
            for i, point in enumerate(key_points, 1):
                f.write(f"{i}. {point}\n")
            f.write("\n")
        
        # Outro
        f.write("\nOUTRO:\n")
        f.write("-" * 80 + "\n")
        f.write(script_data.get('outro', '') + "\n\n")
        
        # Show Notes
        f.write("\nSHOW NOTES:\n")
        f.write("-" * 80 + "\n")
        f.write(script_data.get('show_notes', blog_excerpt[:200]) + "\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("END OF FILE\n")
        f.write("=" * 80 + "\n")
        f.write("\nUpload this entire file to NotebookLM and ask it to create a podcast script.\n")
    
    return filepath

# -------------------- Blog Update Functions --------------------

def update_blog_with_podcast(blog_slug: str, podcast_url: str, 
                             podcast_title: str = None, 
                             podcast_duration: str = None) -> Dict[str, Any]:
    """
    Update blog post in Supabase with podcast information.
    Note: This assumes your blog_posts table has a 'podcast_url' column.
    If not, you may need to add it or store in a separate table.
    """
    try:
        # Check if blog exists
        existing = supabase.table('blog_posts').select('id, title').eq('slug', blog_slug).execute()
        if not existing.data:
            return {"status": "error", "message": f"Blog with slug '{blog_slug}' not found"}
        
        # Prepare update data
        update_data = {'podcast_url': podcast_url}
        if podcast_title:
            update_data['podcast_title'] = podcast_title
        if podcast_duration:
            update_data['podcast_duration'] = podcast_duration
        
        # Update blog post
        resp = supabase.table('blog_posts').update(update_data).eq('slug', blog_slug).execute()
        
        if resp.data:
            return {
                "status": "success",
                "message": f"Blog updated with podcast: {podcast_url}",
                "blog_title": existing.data[0].get('title', '')
            }
        else:
            return {"status": "error", "message": "Failed to update blog post"}
    except Exception as e:
        return {"status": "error", "message": f"Error updating blog: {e}"}

# -------------------- Main Functions --------------------

def create_podcast_from_csv(csv_path: str, duration_minutes: int = 15) -> Dict[str, Any]:
    """Create podcast script from blog CSV file."""
    print(f"\n📖 Reading blog from: {csv_path}")
    blog_data = read_blog_from_csv(csv_path)
    
    if not blog_data:
        return {"status": "error", "message": "Could not read blog data from CSV"}
    
    blog_title = blog_data.get('title', '')
    blog_content = blog_data.get('content', '')
    blog_excerpt = blog_data.get('excerpt', '')
    blog_slug = blog_data.get('slug', '')
    
    print(f"📝 Blog: {blog_title}")
    print(f"🔁 Generating podcast script (this may take a moment)...")
    
    brand_context = load_brand_context()
    script_data = generate_podcast_script(blog_title, blog_content, blog_excerpt, 
                                         brand_context, duration_minutes)
    
    if script_data.get('status') != 'success':
        return script_data
    
    # Save single comprehensive file for NotebookLM
    notebooklm_filepath = save_comprehensive_notebooklm_file(
        blog_slug, script_data, blog_title, blog_excerpt, blog_content, brand_context
    )
    
    print(f"\n✅ Podcast generation file created successfully!")
    print(f"   File: {notebooklm_filepath}")
    print(f"\n📋 Next Steps:")
    print(f"   1. Go to https://notebooklm.google.com")
    print(f"   2. Create a new notebook")
    print(f"   3. Upload this file: {notebooklm_filepath}")
    print(f"   4. Ask NotebookLM: 'Create a podcast script based on this blog post'")
    print(f"   5. Or ask: 'Generate a conversational podcast episode from the blog content'")
    print(f"\n💡 The file contains everything NotebookLM needs:")
    print(f"   - Blog content")
    print(f"   - Brand context")
    print(f"   - Generated script draft")
    print(f"   - Instructions")
    
    return {
        "status": "success",
        "message": "Podcast generation file created successfully",
        "notebooklm_filepath": notebooklm_filepath,
        "script_data": script_data
    }

def create_podcast_from_slug(slug: str, duration_minutes: int = 15) -> Dict[str, Any]:
    """Create podcast script from blog slug in Supabase."""
    print(f"\n📖 Fetching blog from Supabase: {slug}")
    blog_data = fetch_blog_from_supabase(slug)
    
    if not blog_data:
        return {"status": "error", "message": f"Blog with slug '{slug}' not found in Supabase"}
    
    blog_title = blog_data.get('title', '')
    blog_content = blog_data.get('content', '')
    blog_excerpt = blog_data.get('excerpt', '')
    blog_slug = blog_data.get('slug', slug)
    
    print(f"📝 Blog: {blog_title}")
    print(f"🔁 Generating podcast script (this may take a moment)...")
    
    brand_context = load_brand_context()
    script_data = generate_podcast_script(blog_title, blog_content, blog_excerpt, 
                                         brand_context, duration_minutes)
    
    if script_data.get('status') != 'success':
        return script_data
    
    # Save single comprehensive file for NotebookLM
    notebooklm_filepath = save_comprehensive_notebooklm_file(
        blog_slug, script_data, blog_title, blog_excerpt, blog_content, brand_context
    )
    
    print(f"\n✅ Podcast generation file created successfully!")
    print(f"   File: {notebooklm_filepath}")
    print(f"\n📋 Next Steps:")
    print(f"   1. Go to https://notebooklm.google.com")
    print(f"   2. Create a new notebook")
    print(f"   3. Upload this file: {notebooklm_filepath}")
    print(f"   4. Ask NotebookLM: 'Create a podcast script based on this blog post'")
    print(f"   5. Or ask: 'Generate a conversational podcast episode from the blog content'")
    print(f"\n💡 The file contains everything NotebookLM needs:")
    print(f"   - Blog content")
    print(f"   - Brand context")
    print(f"   - Generated script draft")
    print(f"   - Instructions")
    
    return {
        "status": "success",
        "message": "Podcast generation file created successfully",
        "notebooklm_filepath": notebooklm_filepath,
        "script_data": script_data
    }

# -------------------- Main CLI --------------------

def main():
    import sys
    
    print("🎙️  Podcast Generator from Blog Posts")
    print("=" * 60)
    
    # Check for command line arguments
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        
        # If it's a CSV file path
        if arg.endswith('.csv'):
            result = create_podcast_from_csv(arg)
            if result.get('status') == 'success':
                return 0
            else:
                print(f"\n❌ Error: {result.get('message')}")
                return 1
        
        # If it's a slug
        else:
            result = create_podcast_from_slug(arg)
            if result.get('status') == 'success':
                return 0
            else:
                print(f"\n❌ Error: {result.get('message')}")
                return 1
    
    # Interactive mode
    print("\nSelect source:")
    print("1. From CSV file")
    print("2. From Supabase (by slug)")
    print("3. List available blogs")
    
    try:
        choice = input("\nEnter choice (1-3): ").strip()
        
        if choice == '1':
            csv_path = input("Enter CSV file path: ").strip()
            if not csv_path:
                print("❌ No path provided")
                return 1
            result = create_podcast_from_csv(csv_path)
            if result.get('status') == 'success':
                return 0
            else:
                print(f"\n❌ Error: {result.get('message')}")
                return 1
        
        elif choice == '2':
            slug = input("Enter blog slug: ").strip()
            if not slug:
                print("❌ No slug provided")
                return 1
            result = create_podcast_from_slug(slug)
            if result.get('status') == 'success':
                return 0
            else:
                print(f"\n❌ Error: {result.get('message')}")
                return 1
        
        elif choice == '3':
            blogs = list_available_blogs()
            if not blogs:
                print("\n❌ No blog CSV files found")
                return 1
            
            print(f"\n📚 Found {len(blogs)} blog(s):\n")
            for i, blog in enumerate(blogs, 1):
                print(f"{i}. {blog['filename']}")
                print(f"   Slug: {blog['slug']}")
            
            selection = input(f"\nSelect blog (1-{len(blogs)}) or enter slug: ").strip()
            
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(blogs):
                    result = create_podcast_from_csv(blogs[idx]['path'])
                    if result.get('status') == 'success':
                        return 0
                    else:
                        print(f"\n❌ Error: {result.get('message')}")
                        return 1
            except ValueError:
                # Treat as slug
                result = create_podcast_from_slug(selection)
                if result.get('status') == 'success':
                    return 0
                else:
                    print(f"\n❌ Error: {result.get('message')}")
                    return 1
        
        else:
            print("❌ Invalid choice")
            return 1
    
    except KeyboardInterrupt:
        print("\n\n👋 Cancelled by user")
        return 1
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1

if __name__ == '__main__':
    exit(main())

