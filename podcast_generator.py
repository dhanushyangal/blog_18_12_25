#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
podcast_generator.py

Podcast generation from blog posts:
- Reads blog posts from CSV files or Supabase
- Uses Gemini to generate podcast scripts
- Uses ElevenLabs API to generate podcast audio (MP3 files)
- Stores podcast metadata and can update blog posts

Place in: Fundamentals_level_4/simple_blog_automation_script/
Required .env vars: SUPABASE_URL, SUPABASE_SERVICE_KEY, GEMINI_API_KEY, ELEVENLABS_API_KEY

MP3 Audio Generation Process:
1. Script Generation: Gemini AI creates a structured podcast script (intro, segments, outro)
2. Text Chunking: Long scripts are split into chunks (max 40,000 chars per ElevenLabs request)
3. API Calls: Each chunk is sent to ElevenLabs text-to-speech API with voice settings
4. Audio Combination: MP3 audio chunks are concatenated into a single file
5. File Output: Final MP3 saved to generated_podcasts/ directory

The MP3 files are ready to use - no additional processing needed!
"""

import os
import sys
import json
import csv
import re
import requests
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
from slugify import slugify
from google import genai
from bs4 import BeautifulSoup

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

# Load environment
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-flash")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Default: Rachel voice
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")  # High quality, stable for long-form
ELEVENLABS_GUEST_VOICE_ID = os.getenv("ELEVENLABS_GUEST_VOICE_ID")  # Optional: for conversation mode
ELEVENLABS_PODCAST_MODE = os.getenv("ELEVENLABS_PODCAST_MODE", "bulletin")  # "bulletin" (monologue) or "conversation"

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

# -------------------- ElevenLabs Audio Generation --------------------

"""
HOW MP3 AUDIO GENERATION WORKS (Using ElevenLabs Studio Podcasts API):

1. CONTENT PREPARATION:
   - Blog content is extracted and cleaned
   - Can use full blog content or generated script as source

2. PODCAST PROJECT CREATION:
   - POST to https://api.elevenlabs.io/v1/studio/podcasts
   - Source type: "text" (blog content) or "url" (if blog is published)
   - Mode: "bulletin" (monologue) or "conversation" (host + guest)
   - Quality preset: standard, high, ultra, or ultra_lossless
   - Duration scale: short (<3min), default (3-7min), or long (>7min)

3. AUTOMATIC CONVERSION:
   - ElevenLabs automatically structures content into podcast format
   - Uses LLM to create engaging podcast script (LLM cost covered by ElevenLabs)
   - Generates audio with selected voices
   - Returns project_id for tracking

4. CONVERSION STATUS:
   - Project conversion happens asynchronously
   - Can poll project status or use callback_url for webhook
   - Once converted, project contains downloadable audio

5. AUDIO DOWNLOAD:
   - Download final MP3 from project
   - File is ready to use - professionally formatted podcast!

Benefits of Studio API:
- Automatic podcast structuring (no manual script needed)
- Professional formatting and pacing
- Supports conversation mode (two voices)
- Quality presets and duration controls
- Handles entire pipeline automatically
"""

def create_podcast_project_with_elevenlabs(blog_content: str, blog_title: str, 
                                          blog_excerpt: str = None,
                                          voice_id: str = None, 
                                          guest_voice_id: str = None,
                                          model: str = None,
                                          mode: str = None,
                                          quality_preset: str = "standard",
                                          duration_scale: str = "default",
                                          intro: str = None,
                                          outro: str = None,
                                          instructions_prompt: str = None) -> Dict[str, Any]:
    """
    Create a podcast project using ElevenLabs Studio Podcasts API.
    
    Args:
        blog_content: Full blog content text
        blog_title: Blog title
        blog_excerpt: Optional excerpt
        voice_id: Host voice ID (defaults to ELEVENLABS_VOICE_ID)
        guest_voice_id: Guest voice ID for conversation mode (optional)
        model: Model ID (defaults to ELEVENLABS_MODEL)
        mode: "bulletin" (monologue) or "conversation" (defaults to ELEVENLABS_PODCAST_MODE)
        quality_preset: "standard", "high", "ultra", "ultra_lossless"
        duration_scale: "short", "default", "long"
        intro: Optional intro text (max 1500 chars)
        outro: Optional outro text (max 1500 chars)
        instructions_prompt: Optional style/tone instructions (max 3000 chars)
    
    Returns:
        Dict with 'status', 'project_id', 'project', and 'message'
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "message": "ELEVENLABS_API_KEY not found in environment variables"
        }
    
    voice_id = voice_id or ELEVENLABS_VOICE_ID
    model = model or ELEVENLABS_MODEL
    mode = mode or ELEVENLABS_PODCAST_MODE
    
    url = "https://api.elevenlabs.io/v1/studio/podcasts"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }
    
    # Prepare source - use text type
    source = {
        "type": "text",
        "text": blog_content
    }
    
    # Prepare mode
    if mode == "conversation":
        if not guest_voice_id:
            guest_voice_id = ELEVENLABS_GUEST_VOICE_ID or voice_id  # Fallback to same voice
        mode_config = {
            "type": "conversation",
            "conversation": {
                "host_voice_id": voice_id,
                "guest_voice_id": guest_voice_id
            }
        }
    else:
        # Bulletin mode (monologue)
        mode_config = {
            "type": "bulletin",
            "bulletin": {
                "host_voice_id": voice_id
            }
        }
    
    # Build request payload
    payload = {
        "model_id": model,
        "mode": mode_config,
        "source": source,
        "quality_preset": quality_preset,
        "duration_scale": duration_scale
    }
    
    # Add optional fields
    if intro and len(intro) <= 1500:
        payload["intro"] = intro
    if outro and len(outro) <= 1500:
        payload["outro"] = outro
    if instructions_prompt and len(instructions_prompt) <= 3000:
        payload["instructions_prompt"] = instructions_prompt
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            project = data.get('project', {})
            project_id = project.get('project_id')
            
            return {
                "status": "success",
                "project_id": project_id,
                "project": project,
                "message": f"Podcast project created successfully. Project ID: {project_id}"
            }
        else:
            # Check for specific error types
            error_text = response.text
            try:
                error_data = response.json()
                error_detail = error_data.get('detail', {})
                
                # Check for whitelist/access errors
                if response.status_code == 403:
                    error_message = error_detail.get('message', '')
                    if "invalid_subscription" in str(error_detail) or "whitelisted" in error_message.lower():
                        return {
                            "status": "error",
                            "message": "Studio Podcasts API requires account whitelisting. Your account needs to be explicitly whitelisted by ElevenLabs sales team. Contact sales@elevenlabs.io to request access.",
                            "error_type": "whitelist_required",
                            "error_detail": error_detail
                        }
                
                # Check for permission errors
                if response.status_code == 401:
                    if "missing_permissions" in str(error_detail) or "projects_write" in str(error_detail):
                        return {
                            "status": "error",
                            "message": "API key is missing 'projects_write' permission for Studio Podcasts API",
                            "error_type": "missing_permission",
                            "error_detail": error_detail
                        }
            except:
                pass
            
            return {
                "status": "error",
                "message": f"ElevenLabs API error: {response.status_code} - {error_text}"
            }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error creating podcast project: {str(e)}"
        }

def get_podcast_project_status(project_id: str) -> Dict[str, Any]:
    """
    Get the status of a podcast project.
    
    Args:
        project_id: The project ID from create_podcast_project_with_elevenlabs
    
    Returns:
        Dict with 'status', 'project', and conversion status
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "message": "ELEVENLABS_API_KEY not found"
        }
    
    url = f"https://api.elevenlabs.io/v1/studio/podcasts/{project_id}"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY
    }
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            project = data.get('project', {})
            
            # Check conversion status
            creation_meta = project.get('creation_meta', {})
            conversion_status = creation_meta.get('status', 'unknown')
            
            return {
                "status": "success",
                "project": project,
                "conversion_status": conversion_status,
                "is_ready": conversion_status == "success"
            }
        else:
            return {
                "status": "error",
                "message": f"API error: {response.status_code} - {response.text}"
            }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting project status: {str(e)}"
        }

def download_podcast_audio(project_id: str, output_path: str) -> Dict[str, Any]:
    """
    Download the final podcast audio from a converted project.
    
    Args:
        project_id: The project ID
        output_path: Path to save the MP3 file
    
    Returns:
        Dict with 'status', 'filepath', and 'message'
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "message": "ELEVENLABS_API_KEY not found"
        }
    
    # First check if project is ready
    status_result = get_podcast_project_status(project_id)
    if status_result.get('status') != 'success':
        return status_result
    
    if not status_result.get('is_ready'):
        return {
            "status": "error",
            "message": f"Project not ready yet. Status: {status_result.get('conversion_status')}"
        }
    
    # Get download URL from project
    # Note: You may need to use a different endpoint to get the actual audio download URL
    # This is a placeholder - check ElevenLabs docs for exact download endpoint
    url = f"https://api.elevenlabs.io/v1/studio/podcasts/{project_id}/download"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg"
    }
    
    try:
        response = requests.get(url, headers=headers, stream=True)
        
        if response.status_code == 200:
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return {
                "status": "success",
                "filepath": output_path,
                "message": "Podcast audio downloaded successfully"
            }
        else:
            return {
                "status": "error",
                "message": f"Download error: {response.status_code} - {response.text}"
            }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error downloading audio: {str(e)}"
        }

def generate_audio_with_elevenlabs(text: str, voice_id: str = None, model: str = None, 
                                   output_format: str = "mp3") -> Dict[str, Any]:
    """
    Generate audio from text using ElevenLabs API.
    
    Args:
        text: Text to convert to speech
        voice_id: ElevenLabs voice ID (defaults to ELEVENLABS_VOICE_ID env var)
        model: ElevenLabs model name (defaults to ELEVENLABS_MODEL env var)
        output_format: Audio format (mp3, wav, etc.)
    
    Returns:
        Dict with 'status', 'audio_data' (bytes), and 'message'
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "message": "ELEVENLABS_API_KEY not found in environment variables"
        }
    
    voice_id = voice_id or ELEVENLABS_VOICE_ID
    model = model or ELEVENLABS_MODEL
    
    # ElevenLabs API endpoint
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    
    # Prepare request data
    # For long texts, we'll need to chunk them (ElevenLabs has limits)
    # Turbo v2.5 supports up to 40,000 characters
    max_chunk_size = 40000
    
    try:
        # If text is too long, split into chunks
        if len(text) > max_chunk_size:
            # Split by sentences to avoid cutting words
            sentences = re.split(r'(?<=[.!?])\s+', text)
            chunks = []
            current_chunk = ""
            
            for sentence in sentences:
                if len(current_chunk) + len(sentence) + 1 <= max_chunk_size:
                    current_chunk += sentence + " "
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = sentence + " "
            
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            # Generate audio for each chunk and combine
            audio_parts = []
            for i, chunk in enumerate(chunks):
                print(f"   Generating audio chunk {i+1}/{len(chunks)}...")
                data = {
                    "text": chunk,
                    "model_id": model,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "style": 0.0,
                        "use_speaker_boost": True
                    }
                }
                
                response = requests.post(url, json=data, headers=headers)
                
                if response.status_code == 200:
                    audio_parts.append(response.content)
                else:
                    error_text = response.text
                    try:
                        error_data = response.json()
                        error_detail = error_data.get('detail', {})
                        error_message = error_detail.get('message', error_text)
                        
                        # Check for quota errors
                        if "quota_exceeded" in str(error_detail) or "quota" in error_message.lower():
                            return {
                                "status": "error",
                                "message": f"ElevenLabs quota exceeded: {error_message}",
                                "error_type": "quota_exceeded",
                                "error_detail": error_detail
                            }
                    except:
                        pass
                    
                    return {
                        "status": "error",
                        "message": f"ElevenLabs API error (chunk {i+1}): {response.status_code} - {response.text}"
                    }
            
            # Combine audio parts (simple concatenation for MP3)
            # Note: For production, you might want to use pydub to properly merge audio
            combined_audio = b''.join(audio_parts)
            
            return {
                "status": "success",
                "audio_data": combined_audio,
                "message": f"Generated audio from {len(chunks)} chunks"
            }
        else:
            # Single request for shorter text
            data = {
                "text": text,
                "model_id": model,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "use_speaker_boost": True
                }
            }
            
            response = requests.post(url, json=data, headers=headers)
            
            if response.status_code == 200:
                return {
                    "status": "success",
                    "audio_data": response.content,
                    "message": "Audio generated successfully"
                }
            else:
                error_text = response.text
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', {})
                    error_message = error_detail.get('message', error_text)
                    
                    # Check for quota errors
                    if "quota_exceeded" in str(error_detail) or "quota" in error_message.lower():
                        return {
                            "status": "error",
                            "message": f"ElevenLabs quota exceeded: {error_message}",
                            "error_type": "quota_exceeded",
                            "error_detail": error_detail
                        }
                except:
                    pass
                
                return {
                    "status": "error",
                    "message": f"ElevenLabs API error: {response.status_code} - {response.text}"
                }
    
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error generating audio: {str(e)}"
        }

def generate_audio_from_script_file(script_filepath: str, blog_slug: str = None,
                                    voice_id: str = None, model: str = None) -> Dict[str, Any]:
    """
    Generate podcast audio from an existing script file (bypasses Gemini generation).
    
    Args:
        script_filepath: Path to the existing script .txt file
        blog_slug: Blog slug for output filename (optional, extracted from script if not provided)
        voice_id: Optional voice ID override
        model: Optional model override
    
    Returns:
        Dict with 'status', 'audio_filepath', 'script_filepath', and 'message'
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "message": "ELEVENLABS_API_KEY not found. Audio generation skipped."
        }
    
    if not os.path.exists(script_filepath):
        return {
            "status": "error",
            "message": f"Script file not found: {script_filepath}"
        }
    
    print(f"📖 Reading script from: {script_filepath}")
    
    try:
        with open(script_filepath, 'r', encoding='utf-8') as f:
            script_content = f.read()
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error reading script file: {str(e)}"
        }
    
    # Parse script to extract audio content
    # Look for INTRO, SEGMENT, and OUTRO sections
    # Handle both formats: "INTRO:\n---\n" and "INTRO\n---\n"
    intro_match = re.search(r'INTRO:?\s*\n-{3,}\s*\n(.*?)(?=\n\nSEGMENT|\n\nKEY TAKEAWAYS|\n\nOUTRO|$)', script_content, re.DOTALL | re.IGNORECASE)
    outro_match = re.search(r'OUTRO:?\s*\n-{3,}\s*\n(.*?)(?=\n\nSHOW NOTES|$)', script_content, re.DOTALL | re.IGNORECASE)
    
    # Extract segments - handle format: "SEGMENT 1: Title\n---\ncontent"
    segments = []
    segment_pattern = r'SEGMENT\s+(\d+):?\s+([^\n]+)\s*\n-{3,}\s*\n(.*?)(?=\n\nSEGMENT|\n\nKEY TAKEAWAYS|\n\nOUTRO|$)'
    for match in re.finditer(segment_pattern, script_content, re.DOTALL | re.IGNORECASE):
        segment_num = match.group(1)
        segment_title = match.group(2).strip()
        segment_content = match.group(3).strip()
        segments.append({
            'number': segment_num,
            'title': segment_title,
            'content': segment_content
        })
    
    # Combine script parts for audio
    audio_parts = []
    
    if intro_match:
        intro = intro_match.group(1).strip()
        audio_parts.append(intro)
    
    # Add segments in order
    for segment in sorted(segments, key=lambda x: int(x['number'])):
        audio_parts.append(segment['content'])
    
    if outro_match:
        outro = outro_match.group(1).strip()
        audio_parts.append(outro)
    
    if not audio_parts:
        # Fallback: try to extract everything between INTRO and SHOW NOTES
        fallback_match = re.search(r'INTRO:?\s*\n-+\s*\n(.*?)(?=\n\nSHOW NOTES|$)', script_content, re.DOTALL | re.IGNORECASE)
        if fallback_match:
            full_text = fallback_match.group(1).strip()
            # Remove segment headers
            full_text = re.sub(r'SEGMENT\s+\d+:?\s+[^\n]+\s*\n-+\s*\n', '\n\n', full_text)
            audio_parts = [full_text]
    
    if not audio_parts or not any(part.strip() for part in audio_parts):
        return {
            "status": "error",
            "message": "Could not extract script content from file. Make sure it has INTRO, SEGMENT, and OUTRO sections."
        }
    
    # Combine all parts
    full_script = "\n\n".join(audio_parts)
    
    # Extract blog slug from filename if not provided
    if not blog_slug:
        filename = os.path.basename(script_filepath)
        # Try to extract slug from filename (e.g., podcast_slug_timestamp.txt)
        slug_match = re.search(r'podcast_([^_]+(?:_[^_]+)*)_\d{8}_\d{6}', filename)
        if slug_match:
            blog_slug = slug_match.group(1)
        else:
            # Fallback: use filename without extension
            blog_slug = os.path.splitext(filename)[0]
    
    # Check script length
    script_length = len(full_script)
    estimated_credits = script_length
    
    print(f"📊 Script length: {script_length:,} characters")
    print(f"💰 Estimated credits needed: ~{estimated_credits:,}")
    print(f"🎙️  Converting script to audio with Text-to-Speech API...")
    
    # Generate audio using TTS API
    audio_result = generate_audio_with_elevenlabs(full_script, voice_id, model)
    
    if audio_result.get('status') != 'success':
        # If quota error, provide helpful message
        if audio_result.get('error_type') == 'quota_exceeded':
            error_detail = audio_result.get('error_detail', {})
            error_message = error_detail.get('message', 'Quota exceeded')
            print(f"\n⚠️  QUOTA EXCEEDED:")
            print(f"   {error_message}")
            print(f"\n💡 Solutions:")
            print(f"   1. Wait for your quota to reset (usually monthly)")
            print(f"   2. Upgrade your ElevenLabs plan for more credits")
            print(f"   3. Edit the script file to shorten it: {script_filepath}")
            print(f"      Then run this command again")
        
        return {
            "status": "error",
            "message": audio_result.get('message'),
            "script_filepath": script_filepath,
            "error_type": audio_result.get('error_type')
        }
    
    # Save audio file
    os.makedirs('generated_podcasts', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    audio_filename = f"podcast_{blog_slug}_{timestamp}.mp3"
    audio_filepath = os.path.join('generated_podcasts', audio_filename)
    
    with open(audio_filepath, 'wb') as f:
        f.write(audio_result['audio_data'])
    
    print(f"✅ Audio saved: {audio_filepath}")
    
    return {
        "status": "success",
        "audio_filepath": audio_filepath,
        "script_filepath": script_filepath,
        "message": "Podcast audio generated successfully from script file",
        "method": "tts_from_file"
    }

def generate_podcast_audio_with_tts(blog_content: str, blog_title: str, blog_excerpt: str,
                                    blog_slug: str, brand_context: str = None,
                                    voice_id: str = None, 
                                    model: str = None,
                                    duration_minutes: int = 15) -> Dict[str, Any]:
    """
    Generate podcast audio using Text-to-Speech API (fallback when Studio API is not available).
    First generates a script using Gemini, then converts to audio using TTS API.
    
    Args:
        blog_content: Full blog content text
        blog_title: Blog title
        blog_excerpt: Blog excerpt
        blog_slug: Blog slug for filename
        brand_context: Brand context for script generation
        voice_id: Optional voice ID override
        model: Optional model override
        duration_minutes: Target duration in minutes
    
    Returns:
        Dict with 'status', 'audio_filepath', and 'message'
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "message": "ELEVENLABS_API_KEY not found. Audio generation skipped."
        }
    
    print(f"📝 Step 1: Generating podcast script with Gemini...")
    
    # Generate script first
    if not brand_context:
        brand_context = load_brand_context()
    
    script_data = generate_podcast_script(
        blog_title, blog_content, blog_excerpt, brand_context, duration_minutes
    )
    
    if script_data.get('status') != 'success':
        return {
            "status": "error",
            "message": f"Failed to generate script: {script_data.get('message', 'Unknown error')}"
        }
    
    print(f"✅ Script generated successfully!")
    
    # Save script to file
    os.makedirs('generated_podcasts', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    script_filename = f"podcast_{blog_slug}_{timestamp}.txt"
    script_filepath = os.path.join('generated_podcasts', script_filename)
    
    # Combine script parts for saving
    full_script_parts = []
    
    # Add intro
    intro = script_data.get('intro', '')
    if intro:
        full_script_parts.append(f"=== INTRO ===\n{intro}")
    
    # Add segments
    segments = script_data.get('segments', [])
    for i, segment in enumerate(segments, 1):
        title = segment.get('title', f'Segment {i}')
        content = segment.get('content', '')
        if content:
            full_script_parts.append(f"\n=== SEGMENT {i}: {title} ===\n{content}")
    
    # Add outro
    outro = script_data.get('outro', '')
    if outro:
        full_script_parts.append(f"\n=== OUTRO ===\n{outro}")
    
    # Add metadata
    metadata = []
    if script_data.get('key_points'):
        metadata.append(f"\n=== KEY POINTS ===\n" + "\n".join(f"- {point}" for point in script_data.get('key_points', [])))
    if script_data.get('show_notes'):
        metadata.append(f"\n=== SHOW NOTES ===\n{script_data.get('show_notes', '')}")
    if script_data.get('total_duration_estimate'):
        metadata.append(f"\n=== DURATION ESTIMATE ===\n{script_data.get('total_duration_estimate', '')}")
    
    # Combine all parts
    full_script_text = "\n\n".join(full_script_parts + metadata)
    
    # Save script to file
    with open(script_filepath, 'w', encoding='utf-8') as f:
        f.write(f"PODCAST SCRIPT: {blog_title}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        f.write(full_script_text)
    
    print(f"📄 Script saved: {script_filepath}")
    
    # Prepare script for audio (without metadata)
    full_script = "\n\n".join([intro] + [seg.get('content', '') for seg in segments if seg.get('content')] + [outro])
    
    if not full_script.strip():
        return {
            "status": "error",
            "message": "No script content to convert to audio"
        }
    
    # Check script length and estimate credits needed
    script_length = len(full_script)
    # ElevenLabs charges ~1 credit per character (rough estimate)
    estimated_credits = script_length
    
    print(f"📊 Script length: {script_length:,} characters")
    print(f"💰 Estimated credits needed: ~{estimated_credits:,}")
    print(f"🎙️  Step 2: Converting script to audio with Text-to-Speech API...")
    
    # Generate audio using TTS API
    audio_result = generate_audio_with_elevenlabs(full_script, voice_id, model)
    
    if audio_result.get('status') != 'success':
        # If quota error, provide helpful message
        if audio_result.get('error_type') == 'quota_exceeded':
            error_detail = audio_result.get('error_detail', {})
            error_message = error_detail.get('message', 'Quota exceeded')
            print(f"\n⚠️  QUOTA EXCEEDED:")
            print(f"   {error_message}")
            print(f"\n💡 Solutions:")
            print(f"   1. Wait for your quota to reset (usually monthly)")
            print(f"   2. Upgrade your ElevenLabs plan for more credits")
            print(f"   3. Reduce script length by using a shorter duration")
            print(f"   4. The script has been saved to: {script_filepath}")
            print(f"      You can manually edit it to shorten it, then try again")
        
        return {
            "status": "error",
            "message": audio_result.get('message'),
            "script_filepath": script_filepath,
            "error_type": audio_result.get('error_type')
        }
    
    # Save audio file
    os.makedirs('generated_podcasts', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    audio_filename = f"podcast_{blog_slug}_{timestamp}.mp3"
    audio_filepath = os.path.join('generated_podcasts', audio_filename)
    
    with open(audio_filepath, 'wb') as f:
        f.write(audio_result['audio_data'])
    
    print(f"✅ Audio saved: {audio_filepath}")
    
    return {
        "status": "success",
        "audio_filepath": audio_filepath,
        "script_filepath": script_filepath,
        "message": "Podcast audio generated successfully using Text-to-Speech API",
        "method": "tts_fallback"
    }

def generate_podcast_audio(blog_content: str, blog_title: str, blog_excerpt: str,
                           blog_slug: str, 
                           voice_id: str = None, 
                           guest_voice_id: str = None,
                           model: str = None,
                           mode: str = None,
                           quality_preset: str = "standard",
                           duration_scale: str = "default",
                           max_wait_seconds: int = 300,
                           use_tts_fallback: bool = False) -> Dict[str, Any]:
    """
    Generate complete podcast audio using ElevenLabs Studio Podcasts API.
    
    Args:
        blog_content: Full blog content text
        blog_title: Blog title
        blog_excerpt: Blog excerpt
        blog_slug: Blog slug for filename
        voice_id: Optional host voice ID override
        guest_voice_id: Optional guest voice ID for conversation mode
        model: Optional model override
        mode: "bulletin" (monologue) or "conversation"
        quality_preset: "standard", "high", "ultra", "ultra_lossless"
        duration_scale: "short", "default", "long"
        max_wait_seconds: Maximum time to wait for conversion (default 5 minutes)
        use_tts_fallback: If True, use TTS API directly instead of Studio API
    
    Returns:
        Dict with 'status', 'audio_filepath', 'project_id', and 'message'
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "message": "ELEVENLABS_API_KEY not found. Audio generation skipped."
        }
    
    # If TTS fallback is requested, use that instead
    if use_tts_fallback:
        print(f"🎙️  Using Text-to-Speech API (fallback mode)...")
        brand_context = load_brand_context()
        return generate_podcast_audio_with_tts(
            blog_content=blog_content,
            blog_title=blog_title,
            blog_excerpt=blog_excerpt,
            blog_slug=blog_slug,
            brand_context=brand_context,
            voice_id=voice_id,
            model=model
        )
    
    print(f"🎙️  Creating podcast project with ElevenLabs Studio API...")
    
    # Prepare intro and outro from excerpt
    intro_text = None
    outro_text = None
    if blog_excerpt:
        # Use excerpt as intro context (limit to 1500 chars)
        intro_text = f"Welcome to today's episode about {blog_title}. {blog_excerpt[:1400]}"
    
    # Create podcast project
    project_result = create_podcast_project_with_elevenlabs(
        blog_content=blog_content,
        blog_title=blog_title,
        blog_excerpt=blog_excerpt,
        voice_id=voice_id,
        guest_voice_id=guest_voice_id,
        model=model,
        mode=mode,
        quality_preset=quality_preset,
        duration_scale=duration_scale,
        intro=intro_text,
        outro=outro_text
    )
    
    if project_result.get('status') != 'success':
        # Check if it's a whitelist error - automatically fallback to TTS
        error_type = project_result.get('error_type')
        if error_type == "whitelist_required":
            print(f"\n⚠️  Studio API not available (whitelist required).")
            print(f"🔄 Automatically falling back to Text-to-Speech API...")
            print(f"   (This will generate a script first, then convert to audio)")
            
            brand_context = load_brand_context()
            return generate_podcast_audio_with_tts(
                blog_content=blog_content,
                blog_title=blog_title,
                blog_excerpt=blog_excerpt,
                blog_slug=blog_slug,
                brand_context=brand_context,
                voice_id=voice_id,
                model=model
            )
        
        return project_result
    
    project_id = project_result.get('project_id')
    print(f"✅ Podcast project created: {project_id}")
    print(f"⏳ Waiting for conversion to complete (this may take a few minutes)...")
    
    # Poll for conversion status
    import time
    start_time = time.time()
    check_interval = 10  # Check every 10 seconds
    
    while time.time() - start_time < max_wait_seconds:
        status_result = get_podcast_project_status(project_id)
        
        if status_result.get('status') != 'success':
            return status_result
        
        conversion_status = status_result.get('conversion_status')
        
        if conversion_status == 'success':
            print(f"✅ Conversion complete!")
            break
        elif conversion_status == 'error':
            return {
                "status": "error",
                "message": f"Podcast conversion failed. Check project {project_id} in ElevenLabs dashboard."
            }
        else:
            # Still processing
            elapsed = int(time.time() - start_time)
            print(f"   Still processing... ({elapsed}s elapsed)")
            time.sleep(check_interval)
    else:
        return {
            "status": "error",
            "message": f"Conversion timeout after {max_wait_seconds} seconds. Project ID: {project_id}. Check status manually."
        }
    
    # Download audio
    os.makedirs('generated_podcasts', exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    audio_filename = f"podcast_{blog_slug}_{timestamp}.mp3"
    audio_filepath = os.path.join('generated_podcasts', audio_filename)
    
    print(f"📥 Downloading podcast audio...")
    download_result = download_podcast_audio(project_id, audio_filepath)
    
    if download_result.get('status') != 'success':
        # If download fails, return project info so user can download manually
        return {
            "status": "partial_success",
            "message": f"Project created but download failed. Project ID: {project_id}. Download manually from ElevenLabs dashboard.",
            "project_id": project_id,
            "audio_filepath": None
        }
    
    print(f"✅ Audio saved: {audio_filepath}")
    
    return {
        "status": "success",
        "audio_filepath": audio_filepath,
        "project_id": project_id,
        "message": "Podcast audio generated successfully"
    }

# -------------------- Podcast File Management --------------------

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
    """Create podcast from blog CSV file using ElevenLabs Studio Podcasts API."""
    print(f"\n📖 Reading blog from: {csv_path}")
    blog_data = read_blog_from_csv(csv_path)
    
    if not blog_data:
        return {"status": "error", "message": "Could not read blog data from CSV"}
    
    blog_title = blog_data.get('title', '')
    blog_content = blog_data.get('content', '')
    blog_excerpt = blog_data.get('excerpt', '')
    blog_slug = blog_data.get('slug', '')
    
    print(f"📝 Blog: {blog_title}")
    
    # Generate audio with ElevenLabs Studio Podcasts API
    # The Studio API automatically structures content into a podcast
    print(f"\n🎙️  Generating podcast with ElevenLabs Studio API...")
    print(f"   (This will automatically structure your blog into a professional podcast)")
    
    # Extract plain text from HTML for podcast generation
    plain_blog_text = extract_text_from_html(blog_content)
    
    # Map duration_minutes to duration_scale
    if duration_minutes < 3:
        duration_scale = "short"
    elif duration_minutes > 7:
        duration_scale = "long"
    else:
        duration_scale = "default"
    
    audio_result = generate_podcast_audio(
        blog_content=plain_blog_text,
        blog_title=blog_title,
        blog_excerpt=blog_excerpt,
        blog_slug=blog_slug,
        duration_scale=duration_scale
    )
    audio_filepath = audio_result.get('audio_filepath') if audio_result.get('status') == 'success' else None
    
    if audio_filepath:
        print(f"\n✅ Podcast audio generated successfully!")
        print(f"   📁 Audio file: {audio_filepath}")
        print(f"\n💡 Your MP3 podcast is ready to use!")
    else:
        error_msg = audio_result.get('message', 'Unknown error')
        error_type = audio_result.get('error_type')
        
        print(f"\n❌ Audio generation failed: {error_msg}")
        
        # Show helpful messages for specific error types
        if error_type == "whitelist_required" or "whitelisted" in error_msg.lower() or "invalid_subscription" in error_msg:
            print(f"\n⚠️  WHITELIST REQUIRED:")
            print(f"   The Studio Podcasts API is currently in beta/whitelist-only access.")
            print(f"   Your account needs to be explicitly whitelisted by ElevenLabs.")
            print(f"\n💡 Options:")
            print(f"   Option A - Get Studio API access:")
            print(f"   1. Contact ElevenLabs sales team to request Studio API access")
            print(f"   2. Visit: https://elevenlabs.io/contact or email sales@elevenlabs.io")
            print(f"   3. Mention you need access to the Studio Podcasts API")
            print(f"   4. Once whitelisted, your existing API key will work")
            print(f"\n   Option B - Use Text-to-Speech API (works now):")
            print(f"   The code will automatically fallback to TTS API when Studio API fails.")
            print(f"   Or use option 5 in the menu to use TTS directly.")
        elif error_type == "missing_permission" or "missing_permissions" in error_msg or "projects_write" in error_msg:
            print(f"\n⚠️  PERMISSION ERROR DETECTED:")
            print(f"   Your API key doesn't have 'projects_write' permission for Studio Podcasts API.")
            print(f"\n💡 To fix this:")
            print(f"   1. Go to: https://elevenlabs.io/app/settings/api-keys")
            print(f"   2. Check your ElevenLabs plan - Studio Podcasts API requires Creator or Pro plan")
            print(f"   3. Create a new API key with proper permissions")
            print(f"   4. Update ELEVENLABS_API_KEY in your .env file")
            print(f"\n   Or upgrade your plan at: https://elevenlabs.io/pricing")
        
        return {
            "status": "error",
            "message": f"Audio generation failed: {error_msg}",
            "audio_filepath": None
        }
    
    return {
        "status": "success",
        "message": "Podcast generation completed successfully",
        "audio_filepath": audio_filepath,
        "project_id": audio_result.get('project_id')
    }

def create_podcast_from_slug(slug: str, duration_minutes: int = 15) -> Dict[str, Any]:
    """Create podcast from blog slug in Supabase using ElevenLabs Studio Podcasts API."""
    print(f"\n📖 Fetching blog from Supabase: {slug}")
    blog_data = fetch_blog_from_supabase(slug)
    
    if not blog_data:
        return {"status": "error", "message": f"Blog with slug '{slug}' not found in Supabase"}
    
    blog_title = blog_data.get('title', '')
    blog_content = blog_data.get('content', '')
    blog_excerpt = blog_data.get('excerpt', '')
    blog_slug = blog_data.get('slug', slug)
    
    print(f"📝 Blog: {blog_title}")
    
    # Generate audio with ElevenLabs Studio Podcasts API
    # The Studio API automatically structures content into a podcast
    print(f"\n🎙️  Generating podcast with ElevenLabs Studio API...")
    print(f"   (This will automatically structure your blog into a professional podcast)")
    
    # Extract plain text from HTML for podcast generation
    plain_blog_text = extract_text_from_html(blog_content)
    
    # Map duration_minutes to duration_scale
    if duration_minutes < 3:
        duration_scale = "short"
    elif duration_minutes > 7:
        duration_scale = "long"
    else:
        duration_scale = "default"
    
    audio_result = generate_podcast_audio(
        blog_content=plain_blog_text,
        blog_title=blog_title,
        blog_excerpt=blog_excerpt,
        blog_slug=blog_slug,
        duration_scale=duration_scale
    )
    audio_filepath = audio_result.get('audio_filepath') if audio_result.get('status') == 'success' else None
    
    if audio_filepath:
        print(f"\n✅ Podcast audio generated successfully!")
        print(f"   📁 Audio file: {audio_filepath}")
        print(f"\n💡 Your MP3 podcast is ready to use!")
    else:
        error_msg = audio_result.get('message', 'Unknown error')
        error_type = audio_result.get('error_type')
        
        print(f"\n❌ Audio generation failed: {error_msg}")
        
        # Show helpful messages for specific error types
        if error_type == "whitelist_required" or "whitelisted" in error_msg.lower() or "invalid_subscription" in error_msg:
            print(f"\n⚠️  WHITELIST REQUIRED:")
            print(f"   The Studio Podcasts API is currently in beta/whitelist-only access.")
            print(f"   Your account needs to be explicitly whitelisted by ElevenLabs.")
            print(f"\n💡 Options:")
            print(f"   Option A - Get Studio API access:")
            print(f"   1. Contact ElevenLabs sales team to request Studio API access")
            print(f"   2. Visit: https://elevenlabs.io/contact or email sales@elevenlabs.io")
            print(f"   3. Mention you need access to the Studio Podcasts API")
            print(f"   4. Once whitelisted, your existing API key will work")
            print(f"\n   Option B - Use Text-to-Speech API (works now):")
            print(f"   The code will automatically fallback to TTS API when Studio API fails.")
            print(f"   Or use option 5 in the menu to use TTS directly.")
        elif error_type == "missing_permission" or "missing_permissions" in error_msg or "projects_write" in error_msg:
            print(f"\n⚠️  PERMISSION ERROR DETECTED:")
            print(f"   Your API key doesn't have 'projects_write' permission for Studio Podcasts API.")
            print(f"\n💡 To fix this:")
            print(f"   1. Go to: https://elevenlabs.io/app/settings/api-keys")
            print(f"   2. Check your ElevenLabs plan - Studio Podcasts API requires Creator or Pro plan")
            print(f"   3. Create a new API key with proper permissions")
            print(f"   4. Update ELEVENLABS_API_KEY in your .env file")
            print(f"\n   Or upgrade your plan at: https://elevenlabs.io/pricing")
        
        return {
            "status": "error",
            "message": f"Audio generation failed: {error_msg}",
            "audio_filepath": None
        }
    
    return {
        "status": "success",
        "message": "Podcast generation completed successfully",
        "audio_filepath": audio_filepath,
        "project_id": audio_result.get('project_id')
    }

# -------------------- API Key Permission Check --------------------

def check_elevenlabs_api_permissions() -> Dict[str, Any]:
    """
    Check if the ElevenLabs API key has the required permissions for Studio Podcasts API.
    
    Returns:
        Dict with 'status', 'has_permission', 'message', and 'permissions'
    """
    if not ELEVENLABS_API_KEY:
        return {
            "status": "error",
            "has_permission": False,
            "message": "ELEVENLABS_API_KEY not found in environment variables",
            "permissions": []
        }
    
    # Try to get user info to check permissions
    url = "https://api.elevenlabs.io/v1/user"
    
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY
    }
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            user_data = response.json()
            
            # Try to create a test project to check permissions
            test_url = "https://api.elevenlabs.io/v1/studio/podcasts"
            test_payload = {
                "model_id": "eleven_multilingual_v2",
                "mode": {
                    "type": "bulletin",
                    "bulletin": {
                        "host_voice_id": ELEVENLABS_VOICE_ID
                    }
                },
                "source": {
                    "type": "text",
                    "text": "Test"
                }
            }
            
            test_response = requests.post(test_url, json=test_payload, headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json"
            })
            
            if test_response.status_code == 200:
                # Success - has permission, clean up test project
                project_data = test_response.json()
                project_id = project_data.get('project', {}).get('project_id')
                if project_id:
                    # Try to delete test project (optional)
                    delete_url = f"https://api.elevenlabs.io/v1/studio/podcasts/{project_id}"
                    requests.delete(delete_url, headers=headers)
                
                return {
                    "status": "success",
                    "has_permission": True,
                    "message": "API key has 'projects_write' permission for Studio Podcasts API",
                    "permissions": ["projects_write"]
                }
            elif test_response.status_code == 401:
                error_data = test_response.json()
                error_detail = error_data.get('detail', {})
                
                if "missing_permissions" in str(error_detail) or "projects_write" in str(error_detail):
                    return {
                        "status": "success",
                        "has_permission": False,
                        "message": "API key is missing 'projects_write' permission for Studio Podcasts API",
                        "permissions": [],
                        "error": error_detail
                    }
                else:
                    return {
                        "status": "error",
                        "has_permission": False,
                        "message": f"API authentication error: {error_detail}",
                        "permissions": []
                    }
            elif test_response.status_code == 403:
                error_data = test_response.json()
                error_detail = error_data.get('detail', {})
                error_message = error_detail.get('message', '')
                
                if "invalid_subscription" in str(error_detail) or "whitelisted" in error_message.lower():
                    return {
                        "status": "success",
                        "has_permission": False,
                        "message": "Studio Podcasts API requires account whitelisting. Your account needs to be explicitly whitelisted by ElevenLabs sales team.",
                        "permissions": [],
                        "error": error_detail,
                        "requires_whitelist": True
                    }
                else:
                    return {
                        "status": "error",
                        "has_permission": False,
                        "message": f"API access denied (403): {error_message}",
                        "permissions": [],
                        "error": error_detail
                    }
            else:
                return {
                    "status": "error",
                    "has_permission": False,
                    "message": f"Unexpected API response: {test_response.status_code} - {test_response.text}",
                    "permissions": []
                }
        else:
            return {
                "status": "error",
                "has_permission": False,
                "message": f"Failed to authenticate API key: {response.status_code} - {response.text}",
                "permissions": []
            }
    
    except Exception as e:
        return {
            "status": "error",
            "has_permission": False,
            "message": f"Error checking permissions: {str(e)}",
            "permissions": []
    }

# -------------------- Main CLI --------------------

def main():
    import sys
    
    print("🎙️  Podcast Generator from Blog Posts")
    print("=" * 60)
    
    # Check for command line arguments
    if len(sys.argv) > 1:
        # Special command: check API permissions
        if sys.argv[1] == "--check-permissions" or sys.argv[1] == "-c":
            print("\n🔍 Checking ElevenLabs API key permissions...")
            print("-" * 60)
            
            permission_result = check_elevenlabs_api_permissions()
            
            if permission_result.get('status') == 'success':
                if permission_result.get('has_permission'):
                    print("✅ SUCCESS: Your API key has the required permissions!")
                    print(f"   {permission_result.get('message')}")
                    print(f"\n   Permissions: {', '.join(permission_result.get('permissions', []))}")
                    print("\n💡 You can now use the Studio Podcasts API to generate podcasts.")
                else:
                    print("❌ ACCESS ERROR: Your account doesn't have access to Studio Podcasts API!")
                    print(f"   {permission_result.get('message')}")
                    
                    if permission_result.get('requires_whitelist'):
                        print("\n⚠️  WHITELIST REQUIRED:")
                        print("   The Studio Podcasts API is currently in beta/whitelist-only access.")
                        print("   Your account needs to be explicitly whitelisted by ElevenLabs.")
                        print("\n💡 To get access:")
                        print("   1. Contact ElevenLabs sales team to request Studio API access")
                        print("   2. Visit: https://elevenlabs.io/contact or email sales@elevenlabs.io")
                        print("   3. Mention you need access to the Studio Podcasts API")
                        print("   4. Once whitelisted, your existing API key will work")
                    else:
                        print("\n💡 To fix this:")
                        print("   1. Go to: https://elevenlabs.io/app/settings/api-keys")
                        print("   2. Check your ElevenLabs plan - Studio Podcasts API requires Creator or Pro plan")
                        print("   3. Create a new API key with proper permissions")
                        print("   4. Update ELEVENLABS_API_KEY in your .env file")
                        print("\n   Or upgrade your plan at: https://elevenlabs.io/pricing")
            else:
                print(f"❌ Error checking permissions: {permission_result.get('message')}")
            
            return 0 if permission_result.get('has_permission') else 1
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
    print("1. From CSV file (Studio API)")
    print("2. From Supabase (by slug) (Studio API)")
    print("3. List available blogs")
    print("4. Check API key permissions")
    print("5. Generate podcast using Text-to-Speech API (works without whitelist)")
    print("6. Generate audio from existing script file (bypass Gemini)")
    
    try:
        choice = input("\nEnter choice (1-6): ").strip()
        
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
        
        elif choice == '4':
            print("\n🔍 Checking ElevenLabs API key permissions...")
            print("-" * 60)
            
            permission_result = check_elevenlabs_api_permissions()
            
            if permission_result.get('status') == 'success':
                if permission_result.get('has_permission'):
                    print("✅ SUCCESS: Your API key has the required permissions!")
                    print(f"   {permission_result.get('message')}")
                    print(f"\n   Permissions: {', '.join(permission_result.get('permissions', []))}")
                    print("\n💡 You can now use the Studio Podcasts API to generate podcasts.")
                else:
                    print("❌ ACCESS ERROR: Your account doesn't have access to Studio Podcasts API!")
                    print(f"   {permission_result.get('message')}")
                    
                    if permission_result.get('requires_whitelist'):
                        print("\n⚠️  WHITELIST REQUIRED:")
                        print("   The Studio Podcasts API is currently in beta/whitelist-only access.")
                        print("   Your account needs to be explicitly whitelisted by ElevenLabs.")
                        print("\n💡 To get access:")
                        print("   1. Contact ElevenLabs sales team to request Studio API access")
                        print("   2. Visit: https://elevenlabs.io/contact or email sales@elevenlabs.io")
                        print("   3. Mention you need access to the Studio Podcasts API")
                        print("   4. Once whitelisted, your existing API key will work")
                    else:
                        print("\n💡 To fix this:")
                        print("   1. Go to: https://elevenlabs.io/app/settings/api-keys")
                        print("   2. Check your ElevenLabs plan - Studio Podcasts API requires Creator or Pro plan")
                        print("   3. Create a new API key with proper permissions")
                        print("   4. Update ELEVENLABS_API_KEY in your .env file")
                        print("\n   Or upgrade your plan at: https://elevenlabs.io/pricing")
            else:
                print(f"❌ Error checking permissions: {permission_result.get('message')}")
            
            return 0 if permission_result.get('has_permission') else 1
        
        elif choice == '5':
            # Use TTS API directly
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
                    csv_path = blogs[idx]['path']
                else:
                    print("❌ Invalid selection")
                    return 1
            except ValueError:
                # Treat as slug - fetch from Supabase
                blog_data = fetch_blog_from_supabase(selection)
                if not blog_data:
                    print(f"❌ Blog with slug '{selection}' not found")
                    return 1
                
                blog_title = blog_data.get('title', '')
                blog_content = blog_data.get('content', '')
                blog_excerpt = blog_data.get('excerpt', '')
                blog_slug = blog_data.get('slug', selection)
                
                print(f"📝 Blog: {blog_title}")
                print(f"\n🎙️  Generating podcast using Text-to-Speech API...")
                
                brand_context = load_brand_context()
                plain_blog_text = extract_text_from_html(blog_content)
                
                audio_result = generate_podcast_audio_with_tts(
                    blog_content=plain_blog_text,
                    blog_title=blog_title,
                    blog_excerpt=blog_excerpt,
                    blog_slug=blog_slug,
                    brand_context=brand_context
                )
                
                if audio_result.get('status') == 'success':
                    print(f"\n✅ Podcast audio generated successfully!")
                    print(f"   📁 Audio file: {audio_result.get('audio_filepath')}")
                    if audio_result.get('script_filepath'):
                        print(f"   📄 Script file: {audio_result.get('script_filepath')}")
                    return 0
                else:
                    print(f"\n❌ Error: {audio_result.get('message')}")
                    if audio_result.get('script_filepath'):
                        print(f"   📄 Script saved to: {audio_result.get('script_filepath')}")
                        print(f"   💡 You can review/edit the script and try again")
                    return 1
            
            # Read from CSV
            blog_data = read_blog_from_csv(csv_path)
            if not blog_data:
                print("❌ Could not read blog data from CSV")
                return 1
            
            blog_title = blog_data.get('title', '')
            blog_content = blog_data.get('content', '')
            blog_excerpt = blog_data.get('excerpt', '')
            blog_slug = blog_data.get('slug', '')
            
            print(f"📝 Blog: {blog_title}")
            print(f"\n🎙️  Generating podcast using Text-to-Speech API...")
            
            brand_context = load_brand_context()
            plain_blog_text = extract_text_from_html(blog_content)
            
            audio_result = generate_podcast_audio_with_tts(
                blog_content=plain_blog_text,
                blog_title=blog_title,
                blog_excerpt=blog_excerpt,
                blog_slug=blog_slug,
                brand_context=brand_context
            )
            
            if audio_result.get('status') == 'success':
                print(f"\n✅ Podcast audio generated successfully!")
                print(f"   📁 Audio file: {audio_result.get('audio_filepath')}")
                if audio_result.get('script_filepath'):
                    print(f"   📄 Script file: {audio_result.get('script_filepath')}")
                return 0
            else:
                print(f"\n❌ Error: {audio_result.get('message')}")
                if audio_result.get('script_filepath'):
                    print(f"   📄 Script saved to: {audio_result.get('script_filepath')}")
                    print(f"   💡 You can review/edit the script and try again")
                return 1
        
        elif choice == '6':
            # Generate audio from existing script file
            script_path = input("Enter path to script file (.txt): ").strip()
            if not script_path:
                print("❌ No script file path provided")
                return 1
            
            if not script_path.endswith('.txt'):
                print("⚠️  Warning: File doesn't end with .txt, continuing anyway...")
            
            # Extract blog slug from filename if possible
            filename = os.path.basename(script_path)
            slug_match = re.search(r'podcast_([^_]+(?:_[^_]+)*)_\d{8}_\d{6}', filename) or re.search(r'notebooklm_([^_]+(?:_[^_]+)*)_\d{8}_\d{6}', filename)
            blog_slug = slug_match.group(1) if slug_match else None
            
            audio_result = generate_audio_from_script_file(
                script_filepath=script_path,
                blog_slug=blog_slug
            )
            
            if audio_result.get('status') == 'success':
                print(f"\n✅ Podcast audio generated successfully!")
                print(f"   📁 Audio file: {audio_result.get('audio_filepath')}")
                print(f"   📄 Script file: {audio_result.get('script_filepath')}")
                return 0
            else:
                print(f"\n❌ Error: {audio_result.get('message')}")
                if audio_result.get('script_filepath'):
                    print(f"   📄 Script file: {audio_result.get('script_filepath')}")
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

