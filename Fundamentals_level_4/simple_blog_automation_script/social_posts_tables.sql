-- SQL for LinkedIn and Instagram Posts Tables
-- Run this in your Supabase SQL Editor

-- LinkedIn Posts Table
CREATE TABLE IF NOT EXISTS linkedin_posts (
    id BIGSERIAL PRIMARY KEY,
    blog_post_id BIGINT REFERENCES blog_posts(id) ON DELETE CASCADE,
    blog_slug VARCHAR(255) NOT NULL,
    title VARCHAR(500),
    content TEXT NOT NULL,
    hashtags TEXT[], -- Array of hashtags
    call_to_action VARCHAR(500),
    image_url VARCHAR(500),
    status VARCHAR(50) DEFAULT 'draft', -- draft, scheduled, published
    published_at TIMESTAMPTZ,
    linkedin_post_id VARCHAR(255), -- LinkedIn API post ID if published
    engagement_metrics JSONB, -- Store likes, comments, shares, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Instagram Posts Table
CREATE TABLE IF NOT EXISTS instagram_posts (
    id BIGSERIAL PRIMARY KEY,
    blog_post_id BIGINT REFERENCES blog_posts(id) ON DELETE CASCADE,
    blog_slug VARCHAR(255) NOT NULL,
    caption TEXT NOT NULL,
    hashtags TEXT[], -- Array of hashtags
    image_url VARCHAR(500),
    alt_text VARCHAR(500),
    status VARCHAR(50) DEFAULT 'draft', -- draft, scheduled, published
    published_at TIMESTAMPTZ,
    instagram_post_id VARCHAR(255), -- Instagram API post ID if published
    engagement_metrics JSONB, -- Store likes, comments, saves, etc.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_linkedin_posts_blog_post_id ON linkedin_posts(blog_post_id);
CREATE INDEX IF NOT EXISTS idx_linkedin_posts_blog_slug ON linkedin_posts(blog_slug);
CREATE INDEX IF NOT EXISTS idx_linkedin_posts_status ON linkedin_posts(status);
CREATE INDEX IF NOT EXISTS idx_linkedin_posts_published_at ON linkedin_posts(published_at);

CREATE INDEX IF NOT EXISTS idx_instagram_posts_blog_post_id ON instagram_posts(blog_post_id);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_blog_slug ON instagram_posts(blog_slug);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_status ON instagram_posts(status);
CREATE INDEX IF NOT EXISTS idx_instagram_posts_published_at ON instagram_posts(published_at);

-- Add updated_at trigger function (if not exists)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create triggers for updated_at
DROP TRIGGER IF EXISTS update_linkedin_posts_updated_at ON linkedin_posts;
CREATE TRIGGER update_linkedin_posts_updated_at
    BEFORE UPDATE ON linkedin_posts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_instagram_posts_updated_at ON instagram_posts;
CREATE TRIGGER update_instagram_posts_updated_at
    BEFORE UPDATE ON instagram_posts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add comments for documentation
COMMENT ON TABLE linkedin_posts IS 'Stores LinkedIn posts generated from blog posts';
COMMENT ON TABLE instagram_posts IS 'Stores Instagram posts generated from blog posts';
COMMENT ON COLUMN linkedin_posts.blog_post_id IS 'Foreign key reference to blog_posts table';
COMMENT ON COLUMN instagram_posts.blog_post_id IS 'Foreign key reference to blog_posts table';
