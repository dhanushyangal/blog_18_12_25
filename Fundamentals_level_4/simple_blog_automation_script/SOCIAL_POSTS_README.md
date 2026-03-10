# Social Media Posts Generator

This module generates LinkedIn and Instagram posts from blog posts using Google Gemini AI and saves them to Supabase.

## Setup

### 1. Database Setup

Run the SQL script in your Supabase SQL Editor to create the required tables:

```sql
-- Run this file in Supabase SQL Editor
social_posts_tables.sql
```

This will create:
- `linkedin_posts` table
- `instagram_posts` table
- Indexes and triggers for optimal performance

### 2. Environment Variables

Ensure your `.env` file contains:

```env
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_KEY=your_supabase_service_key
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=models/gemini-2.5-flash  # Optional, defaults to this
```

### 3. Dependencies

All required dependencies should already be in `requirements.txt`:
- `google-genai` (for Gemini AI)
- `supabase` (for database operations)
- `beautifulsoup4` (for HTML parsing)
- `python-dotenv` (for environment variables)

## Usage

### Command Line

Generate both LinkedIn and Instagram posts for a blog:

```bash
python social_posts_generator.py <blog_slug>
```

Generate only LinkedIn post:

```bash
python social_posts_generator.py <blog_slug> --linkedin-only
```

Generate only Instagram post:

```bash
python social_posts_generator.py <blog_slug> --instagram-only
```

### Python API

```python
from social_posts_generator import generate_and_save_social_posts

# Generate both posts
results = generate_and_save_social_posts('my-blog-post-slug')

# Generate only LinkedIn
results = generate_and_save_social_posts('my-blog-post-slug', include_instagram=False)

# Generate only Instagram
results = generate_and_save_social_posts('my-blog-post-slug', include_linkedin=False)
```

### Individual Functions

```python
from social_posts_generator import (
    generate_linkedin_post,
    generate_instagram_post,
    save_linkedin_post_to_supabase,
    save_instagram_post_to_supabase
)

# Generate LinkedIn post
linkedin_result = generate_linkedin_post('my-blog-post-slug')
if linkedin_result['status'] == 'success':
    save_result = save_linkedin_post_to_supabase(
        'my-blog-post-slug',
        linkedin_result['data'],
        image_url='https://example.com/image.jpg',  # Optional
        status='draft'  # or 'scheduled' or 'published'
    )

# Generate Instagram post
instagram_result = generate_instagram_post('my-blog-post-slug')
if instagram_result['status'] == 'success':
    save_result = save_instagram_post_to_supabase(
        'my-blog-post-slug',
        instagram_result['data'],
        image_url='https://example.com/image.jpg',  # Optional
        status='draft'  # or 'scheduled' or 'published'
    )
```

## Database Schema

### LinkedIn Posts Table

| Column | Type | Description |
|--------|------|-------------|
| id | BIGSERIAL | Primary key |
| blog_post_id | BIGINT | Foreign key to blog_posts |
| blog_slug | VARCHAR(255) | Blog post slug |
| title | VARCHAR(500) | Post title |
| content | TEXT | Post content (1300-3000 chars) |
| hashtags | TEXT[] | Array of hashtags |
| call_to_action | VARCHAR(500) | CTA text |
| image_url | VARCHAR(500) | Featured image URL |
| status | VARCHAR(50) | draft, scheduled, published |
| published_at | TIMESTAMPTZ | Publication timestamp |
| linkedin_post_id | VARCHAR(255) | LinkedIn API post ID |
| engagement_metrics | JSONB | Likes, comments, shares |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

### Instagram Posts Table

| Column | Type | Description |
|--------|------|-------------|
| id | BIGSERIAL | Primary key |
| blog_post_id | BIGINT | Foreign key to blog_posts |
| blog_slug | VARCHAR(255) | Blog post slug |
| caption | TEXT | Post caption (max 2200 chars) |
| hashtags | TEXT[] | Array of hashtags (max 30) |
| image_url | VARCHAR(500) | Image URL |
| alt_text | VARCHAR(500) | Image alt text |
| status | VARCHAR(50) | draft, scheduled, published |
| published_at | TIMESTAMPTZ | Publication timestamp |
| instagram_post_id | VARCHAR(255) | Instagram API post ID |
| engagement_metrics | JSONB | Likes, comments, saves |
| created_at | TIMESTAMPTZ | Creation timestamp |
| updated_at | TIMESTAMPTZ | Last update timestamp |

## Features

- **AI-Powered Content**: Uses Gemini AI to create engaging, platform-specific posts
- **Brand-Aware**: Incorporates brand context from `brand_context.txt`
- **SEO Optimized**: Includes relevant hashtags and CTAs
- **Database Integration**: Automatically saves to Supabase
- **Update Support**: Updates existing posts if they already exist
- **Error Handling**: Comprehensive error handling and status reporting

## Post Characteristics

### LinkedIn Posts
- Length: 1300-3000 characters
- Professional tone
- Includes engaging hook
- 3-5 relevant hashtags
- Clear call-to-action
- Blog URL included

### Instagram Posts
- Length: Up to 2200 characters
- Emoji usage for visual appeal
- Line breaks for readability
- 10-15 relevant hashtags
- Friendly, inspiring tone
- Alt text for accessibility

## Querying Posts

### Get LinkedIn posts for a blog

```python
from supabase import create_client

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Get all LinkedIn posts for a blog
posts = supabase.table('linkedin_posts').select('*').eq('blog_slug', 'my-blog-slug').execute()

# Get published posts
published = supabase.table('linkedin_posts').select('*').eq('status', 'published').execute()
```

### Get Instagram posts for a blog

```python
# Get all Instagram posts for a blog
posts = supabase.table('instagram_posts').select('*').eq('blog_slug', 'my-blog-slug').execute()

# Get published posts
published = supabase.table('instagram_posts').select('*').eq('status', 'published').execute()
```

## Troubleshooting

### "Blog with slug 'xxx' not found"
- Ensure the blog post exists in the `blog_posts` table
- Check that the slug matches exactly (case-sensitive)

### "Missing required environment variables"
- Verify your `.env` file has all required variables
- Check that you're running from the correct directory

### "Could not parse post from Gemini response"
- The AI response format may have changed
- Check the raw response in the error message
- You may need to adjust the JSON extraction logic

### Database connection errors
- Verify Supabase credentials are correct
- Check that tables exist (run the SQL script)
- Ensure network connectivity to Supabase

## Integration with Blog Generation

You can integrate this with your blog generation workflow:

```python
from seobot_ai import blog_creator, blog_inserter
from social_posts_generator import generate_and_save_social_posts

# 1. Create blog
blog_result = blog_creator(...)
if blog_result['status'] == 'success':
    # 2. Insert blog
    insert_result = blog_inserter(blog_result['file_path'])
    if insert_result['status'] == 'success':
        # 3. Generate social posts
        slug = blog_result['slug']
        social_result = generate_and_save_social_posts(slug)
        print("Social posts generated:", social_result)
```
