import requests
import os
import time
from random import uniform

# Create pages directory if it doesn't exist
if not os.path.exists('pages'):
    os.makedirs('pages')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://scholar.google.com/',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Connection': 'keep-alive'
}

url_base = "https://scholar.google.com.my/scholar?start="
url_tail = "&q=ChatGPT+Educational+Impact+and+Psychological+Implications&hl=enen&as_sdt=0,5&as_vis=1"

for i in range(1, 11):
    url = f"{url_base}{i}{url_tail}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Save the HTML content to a file
        filename = f"pages/{i}.html"
        with open(filename, 'w', encoding='utf-8') as file:
            file.write(response.text)
        
        print(f"Saved {filename}")
        
        # Add random delay between 2-5 seconds to avoid triggering rate limits
        delay = uniform(2, 5)
        print(f"Waiting for {delay:.2f} seconds...")
        time.sleep(delay)
    
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        print("Retrying in 60 seconds...")
        time.sleep(60)  # Wait longer before retrying
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Save the HTML content to a file
            filename = f"pages/{i}.html"
            with open(filename, 'w', encoding='utf-8') as file:
                file.write(response.text)
            
            print(f"Successfully saved {filename} after retry")
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch {url} even after retry: {e}")
