import os
import json
import requests
import feedparser
import time
import re
import random
import warnings
import logging
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image
from groq import Groq, RateLimitError

# --- SETUP LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
except ImportError:
    pass

# --- CONFIGURATION ---
# Pastikan API Key tersedia. Jika kosong, script berhenti.
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://soccerdaily-alpha.vercel.app"
INDEXNOW_KEY = "b3317ae5f84348fa8c96528a43ab2655"
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "")

if not GROQ_API_KEYS:
    logging.error("❌ FATAL ERROR: Groq API Key is missing! Set env variable GROQ_API_KEY.")
    exit(1)

# --- CONSTANTS ---
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)",
    "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)",
    "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)",
    "Hiroshi Tanaka (Data Scout)",
    "Ben Foster (Sports Journalist)"
]

CATEGORY_URLS = {
    "Transfer News": "https://news.google.com/rss/search?q=football+transfer+news+Fabrizio+Romano+here+we+go+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Premier League": "https://news.google.com/rss/search?q=Premier+League+news+match+result+analysis+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "Champions League": "https://news.google.com/rss/search?q=UEFA+Champions+League+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en",
    "La Liga": "https://news.google.com/rss/search?q=La+Liga+Real+Madrid+Barcelona+news+when:1d&hl=en-GB&gl=GB&ceid=GB:en"
}

VALID_CATEGORIES = list(CATEGORY_URLS.keys())

AUTHORITY_SOURCES = [
    "Transfermarkt", "Sky Sports", "The Athletic", "Opta Analyst",
    "WhoScored", "BBC Sport", "The Guardian", "UEFA Official", "ESPN FC"
]

SOCCER_IMAGES_DB = [
    "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1579952363873-27f3bade9f55?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1574629810360-7efbbe195018?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1624880357913-a8539238245b?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1560272564-c83b66b1ad12?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1518091043644-c1d4457512c6?auto=format&fit=crop&w=1200&q=80"
]

CONTENT_DIR = "content/articles"
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_CATEGORY = 1

# --- UTILS ---
def extract_json_from_text(text):
    """Mencoba mengekstrak JSON valid dari respon LLM yang kotor."""
    try:
        # Cari kurung kurawal terluar
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except json.JSONDecodeError:
        pass
    return None

def get_random_groq_client():
    return Groq(api_key=random.choice(GROQ_API_KEYS))

# --- MEMORY SYSTEM ---
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}/"
    # Keep last 50 links
    if len(memory) > 50:
        memory = dict(list(memory.items())[-50:])
    with open(MEMORY_FILE, 'w') as f:
        json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    # Ambil 3 link random
    if len(items) > 3:
        items = random.sample(items, 3)
    
    formatted_links = []
    for title, url in items:
        formatted_links.append(f"* [{title}]({url})")
    return "\n".join(formatted_links)

# --- RSS & SCRAPER ---
def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except Exception as e:
        logging.error(f"RSS Fetch Error: {e}")
        return None

def scrape_full_content(url):
    # Menggunakan Jina AI untuk mendapatkan konten bersih
    jina_url = f"https://r.jina.ai/{url}"
    headers = {'User-Agent': 'Mozilla/5.0', 'X-No-Cache': 'true'}
    logging.info(f"🕵️ Reading via Jina AI: {url[:40]}...")
    
    try:
        response = requests.get(jina_url, headers=headers, timeout=25)
        if response.status_code == 200:
            text = response.text
            # Cleanups
            clean = re.sub(r'Images:.*', '', text, flags=re.DOTALL)
            clean = re.sub(r'\[.*?\]', '', clean)
            clean = re.sub(r'Title:.*', '', clean)
            clean = re.sub(r'URL:.*', '', clean)
            clean = clean.strip()
            
            if len(clean) > 300:
                return clean[:8000] # Limit context window
    except Exception as e:
        logging.error(f"Scraping Error: {e}")
    return None

# --- IMAGE ENGINE ---
def download_and_optimize_image(keyword, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"
    
    # Pilih gambar secara acak dari DB (bisa diganti dengan API Search Image jika ada)
    selected_url = random.choice(SOCCER_IMAGES_DB)
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        response = requests.get(selected_url, headers=headers, timeout=15)
        if response.status_code == 200:
            img = Image.open(BytesIO(response.content)).convert("RGB")
            # Resize untuk performa web
            img = img.resize((1200, 675), Image.Resampling.LANCZOS)
            
            output_path = os.path.join(IMAGE_DIR, filename)
            img.save(output_path, "WEBP", quality=80)
            return f"/images/{filename}"
    except Exception as e:
        logging.error(f"Image Download Error: {e}")
    
    return "/images/default.webp" # Pastikan Anda memiliki default.webp

# --- INDEXING ---
def submit_to_indexnow(url):
    try:
        requests.post("https://api.indexnow.org/indexnow", json={
            "host": WEBSITE_URL.replace("https://", ""),
            "key": INDEXNOW_KEY,
            "keyLocation": f"{WEBSITE_URL}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }, headers={'Content-Type': 'application/json'}, timeout=10)
        logging.info(f"🚀 IndexNow Sent: {url}")
    except Exception as e:
        logging.warning(f"IndexNow Failed: {e}")

def submit_to_google(url):
    if not GOOGLE_JSON_KEY: return
    try:
        creds = json.loads(GOOGLE_JSON_KEY)
        service = build("indexing", "v3", credentials=ServiceAccountCredentials.from_json_keyfile_dict(creds, ["https://www.googleapis.com/auth/indexing"]))
        service.urlNotifications().publish(body={"url": url, "type": "URL_UPDATED"}).execute()
        logging.info(f"🚀 Google Indexing Sent: {url}")
    except Exception as e:
        logging.warning(f"Google Indexing Failed: {e}")

# --- CONTENT FORMATTER ---
def format_content_structure(text):
    # Inject Ads setelah paragraf/bagian tertentu
    parts = text.split("\n\n")
    if len(parts) > 6:
        parts.insert(3, "\n{{< ad >}}\n")
        parts.insert(6, "\n{{< ad >}}\n")
    elif len(parts) > 3:
        parts.insert(2, "\n{{< ad >}}\n")
        
    text = "\n\n".join(parts)
    
    # Format Q&A agar lebih cantik
    text = re.sub(r'(?i)\*\*Q:\s*(.*?)\*\*', r'\n\n**Q: \1**', text) 
    text = re.sub(r'(?i)\*\*A:\s*(.*?)\*\*', r'\n**A:** \1', text)   
    
    return text

# --- 🤖 AI AGENTS ---

def generate_metadata(original_title, content_snippet, category):
    """Step 1: Analisis konten untuk membuat Judul SEO, Slug, dan Deskripsi."""
    client = get_random_groq_client()
    categories_str = ", ".join(VALID_CATEGORIES)
    
    prompt = f"""
    Analyze this football news snippet: "{content_snippet[:1000]}"...
    Original Title: "{original_title}"
    Target Category: {category} (Must be one of: {categories_str})

    Task:
    1. Create a click-worthy, SEO-optimized title (No clickbait, high authority).
    2. Create a clean URL slug (lowercase, dashes).
    3. Write a meta description (max 150 chars).
    4. Extract 5 LSI keywords.
    5. Choose the best Main Keyword.

    Return JSON ONLY:
    {{
        "title": "New Title Here",
        "slug": "new-title-slug",
        "category": "Selected Category",
        "description": "SEO Description...",
        "keywords": ["tag1", "tag2", "tag3", "tag4", "tag5"],
        "main_keyword": "Focus Keyword",
        "image_alt": "Descriptive Alt Text for Image"
    }}
    """
    
    try:
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.6
        )
        return extract_json_from_text(chat.choices[0].message.content)
    except Exception as e:
        logging.error(f"Groq Metadata Error: {e}")
        return None

def write_full_article(metadata, content_context, internal_links, author, external_sources):
    """Step 2: Menulis artikel lengkap dalam Markdown berdasarkan metadata."""
    client = get_random_groq_client()
    
    sources_str = ", ".join(external_sources)
    
    prompt = f"""
    Role: You are {author}, a professional football journalist.
    Task: Write a comprehensive 800-1000 word article based on the context below.
    
    METADATA:
    Title: {metadata['title']}
    Main Keyword: {metadata['main_keyword']}
    
    CONTEXT (Source Material):
    {content_context}
    
    REQUIREMENTS:
    1. Tone: Professional, analytical, exciting but factual.
    2. Structure:
       - **Hook**: Strong opening paragraph (No "Introduction" label).
       - **H2 Headers**: Use creative subheadings containing keywords.
       - **Key Stats/Details**: Use a Markdown Table if applicable.
       - **Industry Insight**: Quote or reference these sources: {sources_str} (Use realistic but general references if specific quotes aren't in context).
       - **Must Read**: Place these internal links naturally:
         {internal_links}
       - **FAQ Section**: 3 distinct Q&A at the end.
       - **Conclusion**: Summary and future outlook.
    3. Formatting: Use BOLD for key entities. NO hashtags.
    
    Output strictly in MARKDOWN format.
    """
    
    try:
        chat = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, 
            max_tokens=5000 
        )
        return chat.choices[0].message.content
    except Exception as e:
        logging.error(f"Groq Writing Error: {e}")
        return None

# --- MAIN LOOP ---
def main():
    # Buat direktori jika belum ada
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    for category_name, rss_url in CATEGORY_URLS.items():
        logging.info(f"📡 Checking Category: {category_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries:
            continue

        processed_count = 0
        for entry in feed.entries:
            if processed_count >= TARGET_PER_CATEGORY:
                break

            # Cek duplikasi awal via RSS link (kasar)
            # Idealnya cek via DB atau memory, tapi ini cukup untuk simple script
            clean_title = entry.title.split(" - ")[0]
            
            logging.info(f"   🔥 Processing: {clean_title[:40]}...")

            # 1. Scrape Content
            scraped_text = scrape_full_content(entry.link)
            source_data = scraped_text if scraped_text else entry.summary
            
            if not source_data or len(source_data) < 200:
                logging.warning("      ❌ Skipped: Content too short/failed.")
                continue

            # 2. Generate Metadata (JSON)
            meta_data = generate_metadata(clean_title, source_data, category_name)
            if not meta_data:
                continue

            # Cek duplikasi file berdasarkan slug baru
            final_slug = slugify(meta_data.get('slug', clean_title), max_length=60, word_boundary=True)
            file_path = f"{CONTENT_DIR}/{final_slug}.md"
            
            if os.path.exists(file_path):
                logging.info(f"      ⚠️ Skipped: Article already exists ({final_slug})")
                continue

            # 3. Persiapkan Aset & Links
            current_author = random.choice(AUTHOR_PROFILES)
            links_block = get_formatted_internal_links()
            selected_sources = random.sample(AUTHORITY_SOURCES, 3)

            # 4. Tulis Artikel (Markdown)
            article_body = write_full_article(meta_data, source_data, links_block, current_author, selected_sources)
            if not article_body:
                continue

            # 5. Format & Polish Content
            formatted_body = format_content_structure(article_body)
            
            # 6. Handle Image
            img_filename = f"{final_slug}.webp"
            img_path = download_and_optimize_image(meta_data.get('main_keyword', 'football'), img_filename)
            
            # 7. Assemble Frontmatter & Save
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            tags_json = json.dumps(meta_data.get('keywords', []))
            
            footer = f"\n\n---\n*Source: Analysis by {current_author} based on reports from {', '.join(selected_sources)} and [Original Story]({entry.link}).*"

            full_content = f"""---
title: "{meta_data['title']}"
date: {date_now}
author: "{current_author}"
categories: ["{category_name}"]
tags: {tags_json}
featured_image: "{img_path}"
featured_image_alt: "{meta_data.get('image_alt', meta_data['title'])}"
description: "{meta_data.get('description', '')}"
slug: "{final_slug}"
draft: false
---

{formatted_body}
{footer}
"""
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(full_content)
                
                # 8. Post-Processing (Memory & Indexing)
                save_link_to_memory(meta_data['title'], final_slug)
                
                full_url = f"{WEBSITE_URL}/{final_slug}/"
                submit_to_indexnow(full_url)
                submit_to_google(full_url)
                
                logging.info(f"   ✅ Published: {final_slug}")
                processed_count += 1
                
                # Jeda agar tidak terkena Rate Limit API
                time.sleep(5)
                
            except Exception as e:
                logging.error(f"      ❌ Failed to save file: {e}")

if __name__ == "__main__":
    main()
