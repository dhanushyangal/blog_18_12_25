# Using OpenRouter Instead of Gemini

You can use **OpenRouter** with the free model `arcee-ai/trinity-large-preview:free` instead of a Gemini API key for:

- **SEO blog automation** (`seobot_ai.py`)
- **Podcast script generation** (`podcast_generator.py`)
- **Social posts** (`social_posts_generator.py`)

## Setup

1. Get an API key from [OpenRouter](https://openrouter.ai/) (Quickstart / API Keys).
2. In your `.env` in this folder, add:

```env
# OpenRouter (no Gemini key needed)
OPENROUTER_API_KEY=sk-or-v1-your-key-here
OPENROUTER_MODEL=arcee-ai/trinity-large-preview:free
```

3. **Do not set** `GEMINI_API_KEY` if you want to use OpenRouter only. If both are set, OpenRouter is used.

## Optional

- **Different model**: set `OPENROUTER_MODEL` to any [OpenRouter model ID](https://openrouter.ai/docs#models) (e.g. another free or paid model).
- **Keep Gemini as fallback**: set both `OPENROUTER_API_KEY` and `GEMINI_API_KEY`; the script uses OpenRouter when its key is present.

## Security

- **Never commit or share your API keys.** Keep them only in `.env` and add `.env` to `.gitignore`.
- If a key was ever exposed (e.g. in chat or email), revoke it in the provider dashboard and create a new key.
