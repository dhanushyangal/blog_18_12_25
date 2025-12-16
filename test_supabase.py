from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")

supabase = create_client(url, key)

# Test query
res = supabase.table("blog_posts").select("id").limit(1).execute()
print("Table OK:", res)

# Test storage
bucket = supabase.storage.from_("public-blog-images")
resp = bucket.list("blog-images")
print("Storage OK:", resp)
