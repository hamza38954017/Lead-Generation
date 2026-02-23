import os
import requests
from bs4 import BeautifulSoup
import re
import csv
from urllib.parse import urljoin, urlparse
import time
import threading
import glob
from flask import Flask

# ========== CONFIGURATION ==========
REQUEST_DELAY = 1          # Seconds between requests
TIMEOUT = 10               # Request timeout in seconds

# Telegram Credentials
TELEGRAM_BOT_TOKEN = "8349995675:AAE9grCMm22vWOzmAjlDtpRd4iMR8IQiVgA"
TELEGRAM_CHAT_ID = "7369364451"

KEYWORDS = [
    'contact', 'contactus', 'contact-us', 'get-in-touch', 'reach-us',
    'location', 'locations', 'offices', 'find-us',
    'about', 'aboutus', 'about-us', 'company', 'who-we-are',
    'our-story', 'corporate', 'profile',
    'team', 'our-team', 'leadership', 'management', 'staff',
    'support', 'help', 'faq', 'faqs', 'customer-service',
    'imprint', 'legal', 'privacy', 'terms'
]
# ===================================

app = Flask(__name__)

# --- Helper Functions ---
def is_valid_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def extract_emails(text):
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_pattern, text)
    return list(set(e for e in emails if is_valid_email(e)))

def extract_phones(text):
    phone_pattern = r'(\+?\d{1,3}[-.\s]?\(?\d{1,4}?\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}(?:[-.\s]?\d{1,9})?)'
    candidates = re.findall(phone_pattern, text)
    valid = []
    for cand in candidates:
        digits = re.sub(r'\D', '', cand)
        if 7 <= len(digits) <= 13:
            valid.append(cand.strip())
    return list(set(valid))

def normalize_url(url, base):
    full = urljoin(base, url)
    return full.split('#')[0]

def is_internal_link(link, base_domain):
    parsed = urlparse(link)
    return parsed.netloc == base_domain and parsed.scheme in ('http', 'https')

def find_interesting_links(soup, base_url, base_domain):
    links = set()
    for a in soup.find_all('a', href=True):
        full = normalize_url(a['href'], base_url)
        if not is_internal_link(full, base_domain):
            continue
        path = urlparse(full).path.lower()
        if any(keyword in path for keyword in KEYWORDS):
            links.add(full)
    return links

# --- Core Crawling Logic ---
def crawl_website(base_url):
    visited, all_emails, all_phones = set(), set(), set()
    to_visit = [base_url]

    while to_visit:
        url = to_visit.pop(0)
        if url in visited: continue

        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=TIMEOUT)
            if resp.status_code != 200: continue

            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text(separator=' ')

            all_emails.update(extract_emails(text))
            all_phones.update(extract_phones(text))
            visited.add(url)

            if url == base_url:
                domain = urlparse(base_url).netloc
                new_links = find_interesting_links(soup, url, domain)
                for link in new_links:
                    if link not in visited and link not in to_visit:
                        to_visit.append(link)
            time.sleep(REQUEST_DELAY)
        except Exception:
            pass

    return visited, all_emails, all_phones

# --- Telegram Sender ---
def send_to_telegram(message, file_path=None):
    if file_path and os.path.exists(file_path):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'caption': message}, files={'document': f})
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': message})

# --- Background Task ---
def run_scraper_job():
    send_to_telegram("🚀 Scraping started! Reading local .txt files...")
    
    # 1. Find all .txt files in the same directory, EXCEPT requirements.txt
    txt_files = [f for f in glob.glob("*.txt") if f != "requirements.txt"]
    
    if not txt_files:
        send_to_telegram("❌ No .txt files found in the repository.")
        return
        
    send_to_telegram(f"📁 Found {len(txt_files)} file(s): {', '.join(txt_files)}")

    # 2. Extract all URLs from all the text files
    urls = []
    for file in txt_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                # Replace newlines with commas just in case, then split
                content = f.read().replace('\n', ',')
                urls.extend([u.strip() for u in content.split(',') if u.strip()])
        except Exception as e:
            send_to_telegram(f"⚠️ Error reading {file}: {e}")

    # Remove duplicates if any
    urls = list(set(urls))

    if not urls:
        send_to_telegram("❌ Files were found, but no URLs were inside them.")
        return

    # 3. Process the URLs
    csv_file = "scraped_data.csv"
    with open(csv_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['email', 'mobile', 'website'])

        for i, base_url in enumerate(urls, 1):
            if not base_url.startswith(('http://', 'https://')):
                base_url = 'http://' + base_url

            visited, emails, phones = crawl_website(base_url)

            if emails:
                for email in emails:
                    if phones:
                        for phone in phones:
                            writer.writerow([email, phone, base_url])
                    else:
                        writer.writerow([email, '', base_url])
            else:
                for phone in phones:
                    writer.writerow(['', phone, base_url])
                if not phones:
                     writer.writerow(['', '', base_url])
                     
            # Optional: Send a progress update every 50 websites
            if i % 50 == 0:
                send_to_telegram(f"⏳ Progress: Scraped {i}/{len(urls)} websites...")

    # 4. Send final CSV to Telegram
    send_to_telegram(f"✅ Scraping complete! Processed {len(urls)} websites. Here is your data:", csv_file)

# --- Flask Routes ---
@app.route('/')
def home():
    return "Bot is running! Visit /start to begin the scraping process."

@app.route('/start')
def start_scraping():
    thread = threading.Thread(target=run_scraper_job)
    thread.start()
    return "Scraping has been triggered in the background. Check your Telegram!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
