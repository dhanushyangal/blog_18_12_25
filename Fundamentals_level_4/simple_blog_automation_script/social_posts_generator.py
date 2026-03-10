#!/usr/bin/env python3
"""
social_posts_generator.py

Generates LinkedIn and Instagram posts from blog posts using Gemini AI.
Saves posts to Supabase database.

Required .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, and either OPENROUTER_API_KEY or GEMINI_API_KEY
Optional: OPENROUTER_MODEL (default arcee-ai/trinity-large-preview:free), GEMINI_MODEL (default models/gemini-2.5-flash)
"""

import os
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from bs4 import BeautifulSoup

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

def extract_text_from_html(html_content: str) -> str:
    """Extract plain text from HTML content."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    return soup.get_text(separator=' ', strip=True)

def load_brand_context() -> str:
    """Load brand context from file."""
    try:
        with open('brand_context.txt', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "Reconstruct is a Mental Fitness Platform that helps build a routine for everyday mental strength."

def extract_hashtags(text: str) -> List[str]:
    """Extract hashtags from text."""
    hashtags = re.findall(r'#\w+', text)
    # Remove # symbol and return unique hashtags
    return list(set([tag[1:] for tag in hashtags]))

def fetch_blog_from_supabase(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch blog post from Supabase by slug."""
    try:
        resp = supabase.table('blog_posts').select('*').eq('slug', slug).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0]
        return None
    except Exception as e:
        print(f"Error fetching blog from Supabase: {e}")
        return None

def get_blog_post_id(slug: str) -> Optional[int]:
    """Get blog post ID from slug."""
    try:
        resp = supabase.table('blog_posts').select('id').eq('slug', slug).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0]['id']
        return None
    except Exception as e:
        print(f"Error fetching blog ID: {e}")
        return None

def list_available_blogs_from_csv() -> List[Dict[str, Any]]:
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
                    'slug': filename.replace('blog_', '').replace('.csv', '').rsplit('_', 2)[0],
                    'source': 'csv'
                })
    return blogs

def list_available_blogs_from_supabase(limit: int = 50) -> List[Dict[str, Any]]:
    """List all available blog posts from Supabase."""
    try:
        resp = supabase.table('blog_posts').select('slug, title, category, published_at').eq('status', 'published').order('published_at', desc=True).limit(limit).execute()
        if resp.data:
            return [{
                'slug': blog.get('slug', ''),
                'title': blog.get('title', ''),
                'category': blog.get('category', ''),
                'published_at': blog.get('published_at', ''),
                'source': 'supabase'
            } for blog in resp.data]
        return []
    except Exception as e:
        print(f"Error fetching blogs from Supabase: {e}")
        return []


def normalize_blog_slug(user_input: str) -> str:
    """
    Convert user input to a blog slug. Accepts:
    - Slug: mastering-stress-mental-fitness-burnout-prevention
    - CSV path/filename: blog_mastering-stress-..._20260212_164050.csv or full path
    """
    if not user_input or not user_input.strip():
        return user_input.strip()
    s = user_input.strip()
    # Path or filename: take basename
    if "\\" in s or "/" in s:
        s = os.path.basename(s)
    # CSV filename like blog_slug_YYYYMMDD_HHMMSS.csv
    if s.endswith(".csv") and s.lower().startswith("blog_"):
        s = s[:-4].replace("blog_", "", 1).rsplit("_", 2)[0]
    return s

# -------------------- LinkedIn Post Generation --------------------

def generate_linkedin_post(blog_slug: str) -> Dict[str, Any]:
    """
    Generate a LinkedIn post from a blog post using Gemini.
    
    Args:
        blog_slug: Slug of the blog post
        
    Returns:
        Dictionary with status and post data
    """
    try:
        # Fetch blog post
        blog_data = fetch_blog_from_supabase(blog_slug)
        if not blog_data:
            return {"status": "error", "message": f"Blog with slug '{blog_slug}' not found"}
        
        blog_title = blog_data.get('title', '')
        blog_content = blog_data.get('content', '')
        blog_excerpt = blog_data.get('excerpt', '')
        blog_category = blog_data.get('category', '')
        blog_tags = blog_data.get('tags', [])
        
        # Extract plain text from HTML
        plain_text = extract_text_from_html(blog_content)
        
        # Load brand context
        brand_context = load_brand_context()
        
        # Build prompt for LinkedIn post
        linkedin_prompt = f"""You are a social media content creator for Reconstruct, a Mental Fitness Platform.

BRAND CONTEXT:
{brand_context[:1500]}

BLOG POST DETAILS:
Title: {blog_title}
Category: {blog_category}
Excerpt: {blog_excerpt}
Tags: {', '.join(blog_tags) if isinstance(blog_tags, list) else blog_tags}

BLOG CONTENT SUMMARY:
{plain_text[:2000]}

TASK: Create a professional LinkedIn post (1300-3000 characters) that:
1. Starts with an engaging hook that captures attention
2. Highlights key insights from the blog post
3. Uses a professional but conversational tone
4. Includes 3-5 relevant hashtags (without # symbol, just the words)
5. Ends with a clear call-to-action encouraging readers to read the full blog
6. Includes the blog URL: https://reconstructyourmind.com/blog/{blog_slug}

FORMAT: Output ONLY a JSON object with this exact structure:
{{
    "title": "Short title for the post (optional, max 100 chars)",
    "content": "Full LinkedIn post content (1300-3000 characters)",
    "hashtags": ["hashtag1", "hashtag2", "hashtag3"],
    "call_to_action": "Brief CTA text (max 200 chars)"
}}

Do not include any markdown formatting, just plain text. Make it engaging and professional.
"""
        
        print(f"\n🔗 Generating LinkedIn post for: {blog_title}")
        g_text = generate_content(linkedin_prompt)
        if not g_text:
            return {"status": "error", "message": "No content returned from LLM"}
        
        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*"content"[^{}]*\}', g_text, re.DOTALL)
        if not json_match:
            # Try to find any JSON object
            json_match = re.search(r'\{.*\}', g_text, re.DOTALL)
        
        if json_match:
            try:
                post_data = json.loads(json_match.group())
            except json.JSONDecodeError:
                # Try to extract JSON manually
                post_data = extract_json_from_text(g_text)
        else:
            post_data = extract_json_from_text(g_text)
        
        if not post_data or 'content' not in post_data:
            return {"status": "error", "message": "Could not parse LinkedIn post from Gemini response", "raw_response": g_text[:500]}
        
        # Extract hashtags if provided as text
        hashtags = post_data.get('hashtags', [])
        if isinstance(hashtags, str):
            hashtags = extract_hashtags(hashtags)
        elif not isinstance(hashtags, list):
            hashtags = []
        
        # Ensure hashtags don't have # symbol
        hashtags = [tag.replace('#', '') for tag in hashtags if tag]
        
        return {
            "status": "success",
            "data": {
                "title": post_data.get('title', ''),
                "content": post_data.get('content', ''),
                "hashtags": hashtags[:10],  # Limit to 10 hashtags
                "call_to_action": post_data.get('call_to_action', 'Read the full article to learn more.')
            }
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Error generating LinkedIn post: {e}"}

def extract_json_from_text(text: str) -> Optional[Dict]:
    """Extract JSON object from text."""
    # Try to find JSON between markers
    markers = [
        (r'<<<JSON_START>>>', r'<<<JSON_END>>>'),
        (r'```json', r'```'),
        (r'```', r'```')
    ]
    
    for start_marker, end_marker in markers:
        pattern = f'{re.escape(start_marker)}(.*?){re.escape(end_marker)}'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except:
                continue
    
    # Try to find any JSON object
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except:
            pass
    
    return None

# -------------------- Instagram Post Generation --------------------

def generate_instagram_post(blog_slug: str) -> Dict[str, Any]:
    """
    Generate an Instagram post from a blog post using Gemini.
    
    Args:
        blog_slug: Slug of the blog post
        
    Returns:
        Dictionary with status and post data
    """
    try:
        # Fetch blog post
        blog_data = fetch_blog_from_supabase(blog_slug)
        if not blog_data:
            return {"status": "error", "message": f"Blog with slug '{blog_slug}' not found"}
        
        blog_title = blog_data.get('title', '')
        blog_content = blog_data.get('content', '')
        blog_excerpt = blog_data.get('excerpt', '')
        blog_category = blog_data.get('category', '')
        blog_tags = blog_data.get('tags', [])
        
        # Extract plain text from HTML
        plain_text = extract_text_from_html(blog_content)
        
        # Load brand context
        brand_context = load_brand_context()
        
        # Build prompt for Instagram post
        instagram_prompt = f"""You are a social media content creator for Reconstruct, a Mental Fitness Platform.

BRAND CONTEXT:
{brand_context[:1500]}

BLOG POST DETAILS:
Title: {blog_title}
Category: {blog_category}
Excerpt: {blog_excerpt}
Tags: {', '.join(blog_tags) if isinstance(blog_tags, list) else blog_tags}

BLOG CONTENT SUMMARY:
{plain_text[:2000]}

TASK: Create an engaging Instagram post caption (2200 characters max) that:
1. Starts with an attention-grabbing hook (first line is crucial!)
2. Uses emojis strategically to make it visually appealing
3. Includes line breaks for readability (use \\n for new lines)
4. Highlights 2-3 key takeaways from the blog
5. Includes 10-15 relevant hashtags at the end (without # symbol, just the words)
6. Mentions the blog link in bio or includes a call to action
7. Uses a friendly, inspiring, and authentic tone

FORMAT: Output ONLY a JSON object with this exact structure:
{{
    "caption": "Full Instagram caption with line breaks (\\n) and emojis (max 2200 chars)",
    "hashtags": ["hashtag1", "hashtag2", "hashtag3"],
    "alt_text": "Accessible alt text description for the image (max 500 chars)"
}}

Make it engaging, authentic, and aligned with mental fitness and wellness themes.
"""
        
        print(f"\n📸 Generating Instagram post for: {blog_title}")
        g_text = generate_content(instagram_prompt)
        if not g_text:
            return {"status": "error", "message": "No content returned from LLM"}
        
        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*"caption"[^{}]*\}', g_text, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{.*\}', g_text, re.DOTALL)
        
        if json_match:
            try:
                post_data = json.loads(json_match.group())
            except json.JSONDecodeError:
                post_data = extract_json_from_text(g_text)
        else:
            post_data = extract_json_from_text(g_text)
        
        if not post_data or 'caption' not in post_data:
            return {"status": "error", "message": "Could not parse Instagram post from Gemini response", "raw_response": g_text[:500]}
        
        # Extract hashtags
        hashtags = post_data.get('hashtags', [])
        if isinstance(hashtags, str):
            hashtags = extract_hashtags(hashtags)
        elif not isinstance(hashtags, list):
            hashtags = []
        
        # Ensure hashtags don't have # symbol
        hashtags = [tag.replace('#', '') for tag in hashtags if tag]
        
        return {
            "status": "success",
            "data": {
                "caption": post_data.get('caption', ''),
                "hashtags": hashtags[:30],  # Instagram allows up to 30 hashtags
                "alt_text": post_data.get('alt_text', f'Image related to {blog_title}')
            }
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Error generating Instagram post: {e}"}

# -------------------- Save to Supabase --------------------

def save_linkedin_post_to_supabase(blog_slug: str, linkedin_post_data: Dict[str, Any], 
                                   image_url: str = None, status: str = 'draft') -> Dict[str, Any]:
    """
    Save LinkedIn post to Supabase.
    
    Args:
        blog_slug: Slug of the blog post
        linkedin_post_data: Dictionary with title, content, hashtags, call_to_action
        image_url: Optional image URL
        status: Post status (draft, scheduled, published)
        
    Returns:
        Dictionary with status and message
    """
    try:
        # Get blog post ID
        blog_post_id = get_blog_post_id(blog_slug)
        if not blog_post_id:
            return {"status": "error", "message": f"Blog post with slug '{blog_slug}' not found"}
        
        # Check if post already exists
        existing = supabase.table('linkedin_posts').select('id').eq('blog_slug', blog_slug).execute()
        if existing.data:
            # Update existing post
            update_data = {
                'title': linkedin_post_data.get('title', ''),
                'content': linkedin_post_data.get('content', ''),
                'hashtags': linkedin_post_data.get('hashtags', []),
                'call_to_action': linkedin_post_data.get('call_to_action', ''),
                'image_url': image_url or '',
                'status': status,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            resp = supabase.table('linkedin_posts').update(update_data).eq('blog_slug', blog_slug).execute()
            if resp.data:
                return {"status": "success", "message": "LinkedIn post updated successfully", "id": resp.data[0]['id']}
        else:
            # Insert new post
            post_data = {
                'blog_post_id': blog_post_id,
                'blog_slug': blog_slug,
                'title': linkedin_post_data.get('title', ''),
                'content': linkedin_post_data.get('content', ''),
                'hashtags': linkedin_post_data.get('hashtags', []),
                'call_to_action': linkedin_post_data.get('call_to_action', ''),
                'image_url': image_url or '',
                'status': status,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            resp = supabase.table('linkedin_posts').insert(post_data).execute()
            if resp.data:
                return {"status": "success", "message": "LinkedIn post saved successfully", "id": resp.data[0]['id']}
        
        return {"status": "error", "message": "Failed to save LinkedIn post"}
        
    except Exception as e:
        return {"status": "error", "message": f"Error saving LinkedIn post: {e}"}

def save_instagram_post_to_supabase(blog_slug: str, instagram_post_data: Dict[str, Any],
                                    image_url: str = None, status: str = 'draft') -> Dict[str, Any]:
    """
    Save Instagram post to Supabase.
    
    Args:
        blog_slug: Slug of the blog post
        instagram_post_data: Dictionary with caption, hashtags, alt_text
        image_url: Optional image URL
        status: Post status (draft, scheduled, published)
        
    Returns:
        Dictionary with status and message
    """
    try:
        # Get blog post ID
        blog_post_id = get_blog_post_id(blog_slug)
        if not blog_post_id:
            return {"status": "error", "message": f"Blog post with slug '{blog_slug}' not found"}
        
        # Check if post already exists
        existing = supabase.table('instagram_posts').select('id').eq('blog_slug', blog_slug).execute()
        if existing.data:
            # Update existing post
            update_data = {
                'caption': instagram_post_data.get('caption', ''),
                'hashtags': instagram_post_data.get('hashtags', []),
                'alt_text': instagram_post_data.get('alt_text', ''),
                'image_url': image_url or '',
                'status': status,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            resp = supabase.table('instagram_posts').update(update_data).eq('blog_slug', blog_slug).execute()
            if resp.data:
                return {"status": "success", "message": "Instagram post updated successfully", "id": resp.data[0]['id']}
        else:
            # Insert new post
            post_data = {
                'blog_post_id': blog_post_id,
                'blog_slug': blog_slug,
                'caption': instagram_post_data.get('caption', ''),
                'hashtags': instagram_post_data.get('hashtags', []),
                'alt_text': instagram_post_data.get('alt_text', ''),
                'image_url': image_url or '',
                'status': status,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            resp = supabase.table('instagram_posts').insert(post_data).execute()
            if resp.data:
                return {"status": "success", "message": "Instagram post saved successfully", "id": resp.data[0]['id']}
        
        return {"status": "error", "message": "Failed to save Instagram post"}
        
    except Exception as e:
        return {"status": "error", "message": f"Error saving Instagram post: {e}"}

# -------------------- Main Functions --------------------

def generate_and_save_social_posts(blog_slug: str, include_linkedin: bool = True, 
                                   include_instagram: bool = True) -> Dict[str, Any]:
    """
    Generate and save both LinkedIn and Instagram posts for a blog.
    
    Args:
        blog_slug: Slug of the blog post
        include_linkedin: Whether to generate LinkedIn post
        include_instagram: Whether to generate Instagram post
        
    Returns:
        Dictionary with status and results
    """
    results = {
        "status": "success",
        "blog_slug": blog_slug,
        "linkedin": None,
        "instagram": None
    }
    
    # Generate LinkedIn post
    if include_linkedin:
        print(f"\n{'='*60}")
        print("🔗 GENERATING LINKEDIN POST")
        print(f"{'='*60}")
        linkedin_result = generate_linkedin_post(blog_slug)
        if linkedin_result.get('status') == 'success':
            save_result = save_linkedin_post_to_supabase(blog_slug, linkedin_result['data'])
            results['linkedin'] = {
                "generation": linkedin_result,
                "save": save_result
            }
            if save_result.get('status') == 'success':
                print(f"✅ LinkedIn post saved to Supabase (ID: {save_result.get('id')})")
            else:
                print(f"⚠️ LinkedIn post generated but failed to save: {save_result.get('message')}")
        else:
            results['linkedin'] = {"generation": linkedin_result}
            print(f"❌ Failed to generate LinkedIn post: {linkedin_result.get('message')}")
    
    # Generate Instagram post
    if include_instagram:
        print(f"\n{'='*60}")
        print("📸 GENERATING INSTAGRAM POST")
        print(f"{'='*60}")
        instagram_result = generate_instagram_post(blog_slug)
        if instagram_result.get('status') == 'success':
            save_result = save_instagram_post_to_supabase(blog_slug, instagram_result['data'])
            results['instagram'] = {
                "generation": instagram_result,
                "save": save_result
            }
            if save_result.get('status') == 'success':
                print(f"✅ Instagram post saved to Supabase (ID: {save_result.get('id')})")
            else:
                print(f"⚠️ Instagram post generated but failed to save: {save_result.get('message')}")
        else:
            results['instagram'] = {"generation": instagram_result}
            print(f"❌ Failed to generate Instagram post: {instagram_result.get('message')}")
    
    return results

# -------------------- CLI Interface --------------------

def main():
    """Main CLI function."""
    import sys
    
    # Fix Windows console encoding for emoji support
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            # Python < 3.7 fallback
            import codecs
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    
    print("🚀 Social Media Posts Generator")
    print("=" * 60)
    
    # Check for command line arguments
    if len(sys.argv) > 1:
        blog_slug = normalize_blog_slug(sys.argv[1])
        include_linkedin = '--instagram-only' not in sys.argv
        include_instagram = '--linkedin-only' not in sys.argv
        
        print(f"\n📝 Blog Slug: {blog_slug}")
        print(f"🔗 LinkedIn: {'Yes' if include_linkedin else 'No'}")
        print(f"📸 Instagram: {'Yes' if include_instagram else 'No'}")
        
        results = generate_and_save_social_posts(blog_slug, include_linkedin, include_instagram)
        
        print(f"\n{'='*60}")
        print("📊 SUMMARY")
        print(f"{'='*60}")
        
        if results.get('linkedin'):
            linkedin_status = results['linkedin'].get('save', {}).get('status', 'unknown')
            print(f"LinkedIn: {linkedin_status.upper()}")
        
        if results.get('instagram'):
            instagram_status = results['instagram'].get('save', {}).get('status', 'unknown')
            print(f"Instagram: {instagram_status.upper()}")
        
        return 0
    
    # Interactive mode
    print("\nSelect source:")
    print("1. From Supabase (by slug)")
    print("2. List blogs from Supabase")
    print("3. List blogs from CSV files")
    print("4. Enter blog slug directly")
    
    try:
        choice = input("\nEnter choice (1-4): ").strip()
        
        if choice == '1':
            slug = normalize_blog_slug(input("Enter blog slug (e.g. mastering-stress-mental-fitness-burnout-prevention): ").strip())
            if not slug:
                print("❌ No slug provided")
                return 1
            
            # Ask which platforms
            print("\nSelect platforms:")
            print("1. Both LinkedIn and Instagram")
            print("2. LinkedIn only")
            print("3. Instagram only")
            platform_choice = input("Enter choice (1-3, default: 1): ").strip() or '1'
            
            include_linkedin = platform_choice in ['1', '2']
            include_instagram = platform_choice in ['1', '3']
            
            results = generate_and_save_social_posts(slug, include_linkedin, include_instagram)
            
            print(f"\n{'='*60}")
            print("📊 SUMMARY")
            print(f"{'='*60}")
            
            if results.get('linkedin'):
                linkedin_status = results['linkedin'].get('save', {}).get('status', 'unknown')
                print(f"LinkedIn: {linkedin_status.upper()}")
            
            if results.get('instagram'):
                instagram_status = results['instagram'].get('save', {}).get('status', 'unknown')
                print(f"Instagram: {instagram_status.upper()}")
            
            return 0 if results.get('status') == 'success' else 1
        
        elif choice == '2':
            blogs = list_available_blogs_from_supabase()
            if not blogs:
                print("\n❌ No published blogs found in Supabase")
                return 1
            
            print(f"\n📚 Found {len(blogs)} blog(s) in Supabase:\n")
            for i, blog in enumerate(blogs, 1):
                title = blog.get('title', 'N/A')[:60]
                category = blog.get('category', 'N/A')
                print(f"{i}. {title}")
                print(f"   Slug: {blog['slug']} | Category: {category}")
            
            selection = input(f"\nSelect blog (1-{len(blogs)}) or enter slug: ").strip()
            
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(blogs):
                    blog_slug = blogs[idx]['slug']
                else:
                    print("❌ Invalid selection")
                    return 1
            except ValueError:
                # Treat as slug or path/filename
                blog_slug = normalize_blog_slug(selection)
            
            # Ask which platforms
            print("\nSelect platforms:")
            print("1. Both LinkedIn and Instagram")
            print("2. LinkedIn only")
            print("3. Instagram only")
            platform_choice = input("Enter choice (1-3, default: 1): ").strip() or '1'
            
            include_linkedin = platform_choice in ['1', '2']
            include_instagram = platform_choice in ['1', '3']
            
            results = generate_and_save_social_posts(blog_slug, include_linkedin, include_instagram)
            
            print(f"\n{'='*60}")
            print("📊 SUMMARY")
            print(f"{'='*60}")
            
            if results.get('linkedin'):
                linkedin_status = results['linkedin'].get('save', {}).get('status', 'unknown')
                print(f"LinkedIn: {linkedin_status.upper()}")
            
            if results.get('instagram'):
                instagram_status = results['instagram'].get('save', {}).get('status', 'unknown')
                print(f"Instagram: {instagram_status.upper()}")
            
            return 0 if results.get('status') == 'success' else 1
        
        elif choice == '3':
            blogs = list_available_blogs_from_csv()
            if not blogs:
                print("\n❌ No blog CSV files found")
                return 1
            
            print(f"\n📚 Found {len(blogs)} blog CSV file(s):\n")
            for i, blog in enumerate(blogs, 1):
                print(f"{i}. {blog['filename']}")
                print(f"   Slug: {blog['slug']}")
            
            selection = input(f"\nSelect blog (1-{len(blogs)}) or enter slug: ").strip()
            
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(blogs):
                    blog_slug = blogs[idx]['slug']
                else:
                    print("❌ Invalid selection")
                    return 1
            except ValueError:
                # Treat as slug or path/filename
                blog_slug = normalize_blog_slug(selection)
            
            # Ask which platforms
            print("\nSelect platforms:")
            print("1. Both LinkedIn and Instagram")
            print("2. LinkedIn only")
            print("3. Instagram only")
            platform_choice = input("Enter choice (1-3, default: 1): ").strip() or '1'
            
            include_linkedin = platform_choice in ['1', '2']
            include_instagram = platform_choice in ['1', '3']
            
            results = generate_and_save_social_posts(blog_slug, include_linkedin, include_instagram)
            
            print(f"\n{'='*60}")
            print("📊 SUMMARY")
            print(f"{'='*60}")
            
            if results.get('linkedin'):
                linkedin_status = results['linkedin'].get('save', {}).get('status', 'unknown')
                print(f"LinkedIn: {linkedin_status.upper()}")
            
            if results.get('instagram'):
                instagram_status = results['instagram'].get('save', {}).get('status', 'unknown')
                print(f"Instagram: {instagram_status.upper()}")
            
            return 0 if results.get('status') == 'success' else 1
        
        elif choice == '4':
            slug = normalize_blog_slug(input("Enter blog slug or CSV path (e.g. mastering-stress-mental-fitness-burnout-prevention): ").strip())
            if not slug:
                print("❌ No slug provided")
                return 1
            
            # Ask which platforms
            print("\nSelect platforms:")
            print("1. Both LinkedIn and Instagram")
            print("2. LinkedIn only")
            print("3. Instagram only")
            platform_choice = input("Enter choice (1-3, default: 1): ").strip() or '1'
            
            include_linkedin = platform_choice in ['1', '2']
            include_instagram = platform_choice in ['1', '3']
            
            results = generate_and_save_social_posts(slug, include_linkedin, include_instagram)
            
            print(f"\n{'='*60}")
            print("📊 SUMMARY")
            print(f"{'='*60}")
            
            if results.get('linkedin'):
                linkedin_status = results['linkedin'].get('save', {}).get('status', 'unknown')
                print(f"LinkedIn: {linkedin_status.upper()}")
            
            if results.get('instagram'):
                instagram_status = results['instagram'].get('save', {}).get('status', 'unknown')
                print(f"Instagram: {instagram_status.upper()}")
            
            return 0 if results.get('status') == 'success' else 1
        
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
