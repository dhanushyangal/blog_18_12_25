#!/usr/bin/env python3
"""
WordPress Supabase Sync Script

This script syncs blog posts from Supabase directly into WordPress using the WordPress REST API.
It fetches published blogs from Supabase and creates/updates WordPress posts.

Required .env variables:
- SUPABASE_URL
- SUPABASE_SERVICE_KEY (or SUPABASE_PUBLIC_KEY)
- WORDPRESS_URL (e.g., https://yoursite.com)
- WORDPRESS_USERNAME (WordPress admin username)
- WORDPRESS_APPLICATION_PASSWORD (App password, not regular password)
"""

import os
import requests
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

# Load environment
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_PUBLIC_KEY")
WORDPRESS_URL = os.getenv("WORDPRESS_URL", "").rstrip('/')
WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME", "")
WORDPRESS_APP_PASSWORD = os.getenv("WORDPRESS_APPLICATION_PASSWORD", "")

# Validate
if not all([SUPABASE_URL, SUPABASE_SERVICE_KEY]):
    raise ValueError("Missing Supabase credentials. Check .env: SUPABASE_URL, SUPABASE_SERVICE_KEY")

if not all([WORDPRESS_URL, WORDPRESS_USERNAME, WORDPRESS_APP_PASSWORD]):
    raise ValueError("Missing WordPress credentials. Check .env: WORDPRESS_URL, WORDPRESS_USERNAME, WORDPRESS_APPLICATION_PASSWORD")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# WordPress REST API endpoints
WP_API_BASE = f"{WORDPRESS_URL}/wp-json/wp/v2"
WP_POSTS_ENDPOINT = f"{WP_API_BASE}/posts"
WP_MEDIA_ENDPOINT = f"{WP_API_BASE}/media"
WP_CATEGORIES_ENDPOINT = f"{WP_API_BASE}/categories"
WP_TAGS_ENDPOINT = f"{WP_API_BASE}/tags"

# Authentication for WordPress
auth = (WORDPRESS_USERNAME, WORDPRESS_APP_PASSWORD)


def fetch_supabase_blogs(limit: int = 100, status: str = 'published') -> List[Dict[str, Any]]:
    """
    Fetch blog posts from Supabase.
    
    Args:
        limit: Maximum number of blogs to fetch
        status: Blog status filter (default: 'published')
    
    Returns:
        List of blog post dictionaries
    """
    try:
        response = supabase.table('blog_posts').select('*').eq('status', status).order('published_at', desc=True).limit(limit).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching blogs from Supabase: {e}")
        return []


def get_or_create_category(category_name: str) -> Optional[int]:
    """
    Get existing WordPress category or create new one.
    
    Args:
        category_name: Name of the category
    
    Returns:
        Category ID or None
    """
    if not category_name:
        return None
    
    # Check if category exists
    response = requests.get(
        WP_CATEGORIES_ENDPOINT,
        params={'search': category_name, 'per_page': 1},
        auth=auth
    )
    
    if response.status_code == 200:
        categories = response.json()
        if categories:
            return categories[0]['id']
    
    # Create new category
    response = requests.post(
        WP_CATEGORIES_ENDPOINT,
        json={'name': category_name},
        auth=auth
    )
    
    if response.status_code == 201:
        return response.json()['id']
    
    return None


def get_or_create_tag(tag_name: str) -> Optional[int]:
    """
    Get existing WordPress tag or create new one.
    
    Args:
        tag_name: Name of the tag
    
    Returns:
        Tag ID or None
    """
    if not tag_name:
        return None
    
    # Check if tag exists
    response = requests.get(
        WP_TAGS_ENDPOINT,
        params={'search': tag_name, 'per_page': 1},
        auth=auth
    )
    
    if response.status_code == 200:
        tags = response.json()
        if tags:
            return tags[0]['id']
    
    # Create new tag
    response = requests.post(
        WP_TAGS_ENDPOINT,
        json={'name': tag_name},
        auth=auth
    )
    
    if response.status_code == 201:
        return response.json()['id']
    
    return None


def upload_featured_image(image_url: str) -> Optional[int]:
    """
    Upload featured image to WordPress media library.
    
    Args:
        image_url: URL of the image to upload
    
    Returns:
        Media ID or None
    """
    if not image_url:
        return None
    
    try:
        # Download image
        img_response = requests.get(image_url, timeout=30)
        if img_response.status_code != 200:
            return None
        
        # Get filename from URL
        filename = os.path.basename(image_url.split('?')[0])
        if not filename or '.' not in filename:
            filename = f"featured_image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        
        # Upload to WordPress
        files = {'file': (filename, img_response.content, img_response.headers.get('content-type', 'image/jpeg'))}
        
        response = requests.post(
            WP_MEDIA_ENDPOINT,
            files=files,
            data={'title': filename},
            auth=auth
        )
        
        if response.status_code == 201:
            return response.json()['id']
        
        return None
    except Exception as e:
        print(f"Error uploading image {image_url}: {e}")
        return None


def check_post_exists(slug: str) -> Optional[int]:
    """
    Check if WordPress post with given slug already exists.
    
    Args:
        slug: Post slug
    
    Returns:
        Post ID if exists, None otherwise
    """
    response = requests.get(
        WP_POSTS_ENDPOINT,
        params={'slug': slug, 'per_page': 1},
        auth=auth
    )
    
    if response.status_code == 200:
        posts = response.json()
        if posts:
            return posts[0]['id']
    
    return None


def sync_blog_to_wordpress(blog: Dict[str, Any], update_existing: bool = False) -> Dict[str, Any]:
    """
    Sync a single blog post from Supabase to WordPress.
    
    Args:
        blog: Blog post dictionary from Supabase
        update_existing: Whether to update existing posts
    
    Returns:
        Result dictionary with status and message
    """
    try:
        slug = blog.get('slug', '')
        if not slug:
            return {"status": "error", "message": "Blog has no slug"}
        
        # Check if post already exists
        existing_post_id = check_post_exists(slug)
        if existing_post_id and not update_existing:
            return {"status": "skipped", "message": f"Post with slug '{slug}' already exists (use update_existing=True to update)"}
        
        # Prepare WordPress post data
        wp_post_data = {
            'title': blog.get('title', ''),
            'content': blog.get('content', ''),
            'excerpt': blog.get('excerpt', ''),
            'status': 'publish',  # WordPress uses 'publish' instead of 'published'
            'slug': slug,
            'meta': {
                '_yoast_wpseo_title': blog.get('meta_title', ''),
                '_yoast_wpseo_metadesc': blog.get('meta_description', ''),
            }
        }
        
        # Handle featured image
        featured_image_url = blog.get('featured_image', '')
        if featured_image_url:
            media_id = upload_featured_image(featured_image_url)
            if media_id:
                wp_post_data['featured_media'] = media_id
        

        
        # Handle category
        category = blog.get('category', '')
        if category:
            category_id = get_or_create_category(category)
            if category_id:
                wp_post_data['categories'] = [category_id]
        
        # Handle tags
        tags = blog.get('tags', [])
        if isinstance(tags, str):
            # Parse if tags is a string (PostgreSQL array format)
            tags = [tag.strip().strip('"') for tag in tags.strip('{}').split(',') if tag.strip()]
        
        tag_ids = []
        for tag in tags:
            if tag:
                tag_id = get_or_create_tag(tag)
                if tag_id:
                    tag_ids.append(tag_id)
        
        if tag_ids:
            wp_post_data['tags'] = tag_ids
        
        # Set published date
        published_at = blog.get('published_at', '')
        if published_at:
            wp_post_data['date'] = published_at
        
        # Create or update post
        if existing_post_id and update_existing:
            # Update existing post
            response = requests.post(
                f"{WP_POSTS_ENDPOINT}/{existing_post_id}",
                json=wp_post_data,
                auth=auth
            )
            action = "updated"
        else:
            # Create new post
            response = requests.post(
                WP_POSTS_ENDPOINT,
                json=wp_post_data,
                auth=auth
            )
            action = "created"
        
        if response.status_code in [200, 201]:
            post_data = response.json()
            post_url = post_data.get('link', f"{WORDPRESS_URL}/?p={post_data['id']}")
            return {
                "status": "success",
                "message": f"Post {action} successfully",
                "post_id": post_data['id'],
                "post_url": post_url,
                "action": action
            }
        else:
            return {
                "status": "error",
                "message": f"WordPress API error: {response.status_code} - {response.text}"
            }
    
    except Exception as e:
        return {"status": "error", "message": f"Error syncing blog: {e}"}


def sync_latest_blog(update_existing: bool = False) -> Dict[str, Any]:
    """
    Sync only the latest published blog from Supabase to WordPress.
    
    Args:
        update_existing: Whether to update existing posts
    
    Returns:
        Summary dictionary with results
    """
    print("🔄 Fetching latest blog from Supabase...")
    blogs = fetch_supabase_blogs(limit=1)
    
    if not blogs:
        return {"status": "error", "message": "No blogs found in Supabase"}
    
    blog = blogs[0]
    title = blog.get('title', 'Unknown')
    print(f"📝 Latest blog: {title}\n")
    
    print(f"Syncing: {title}")
    result = sync_blog_to_wordpress(blog, update_existing=update_existing)
    
    results = {
        "total": 1,
        "success": 0,
        "updated": 0,
        "created": 0,
        "skipped": 0,
        "errors": 0,
        "details": [{
            "title": title,
            "slug": blog.get('slug', ''),
            **result
        }]
    }
    
    if result["status"] == "success":
        results["success"] += 1
        if result.get("action") == "updated":
            results["updated"] += 1
        else:
            results["created"] += 1
        print(f"   ✅ {result['message']} - {result.get('post_url', '')}\n")
    elif result["status"] == "skipped":
        results["skipped"] += 1
        print(f"   ⏭️  {result['message']}\n")
    else:
        results["errors"] += 1
        print(f"   ❌ {result['message']}\n")
    
    return results


def main():
    """
    Main function to sync blogs from Supabase to WordPress.
    """
    import sys
    
    print("=" * 60)
    print("WordPress Supabase Sync Tool")
    print("=" * 60)
    print("Syncing LATEST blog only")
    print(f"WordPress URL: {WORDPRESS_URL}")
    print(f"Supabase URL: {SUPABASE_URL}\n")
    
    # Check WordPress connection
    print("🔍 Testing WordPress connection...")
    try:
        response = requests.get(f"{WP_API_BASE}", auth=auth, timeout=10)
        if response.status_code == 200:
            print("✅ WordPress connection successful\n")
        else:
            print(f"⚠️  WordPress API returned status {response.status_code}\n")
    except Exception as e:
        print(f"❌ Cannot connect to WordPress: {e}\n")
        return 1
    
    # Get sync options
    update_existing = False
    if len(sys.argv) > 1:
        if sys.argv[1] in ['--update', '-u']:
            update_existing = True
            print("ℹ️  Update mode: Will update existing posts\n")
    
    # Sync only the latest blog
    results = sync_latest_blog(update_existing=update_existing)
    
    # Print summary
    print("\n" + "=" * 60)
    print("Sync Summary")
    print("=" * 60)
    print(f"Total blogs: {results['total']}")
    print(f"✅ Created: {results['created']}")
    print(f"🔄 Updated: {results['updated']}")
    print(f"⏭️  Skipped: {results['skipped']}")
    print(f"❌ Errors: {results['errors']}")
    print("=" * 60)
    
    return 0 if results['errors'] == 0 else 1


if __name__ == '__main__':
    exit(main())

