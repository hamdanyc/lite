import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
from tqdm import tqdm

def search_google_scholar(query, n):
    base_url = "https://scholar.google.com/scholar"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    params = {
        'q': query,
        'start': 0
    }
    results = []

    total_pages = (n + 9) // 10  # Calculate total pages needed
    print(f"Fetching {n} articles. This may take a few minutes...")

    for start in tqdm(range(0, n, 10), total=total_pages, desc="Fetching pages"):
        params['start'] = start
        retry_count = 0
        success = False

        while retry_count < 3 and not success:
            response = requests.get(base_url, params=params, headers=headers)
            if response.status_code == 429:
                retry_count += 1
                delay = 2 ** retry_count + random.uniform(0, 1)  # Exponential backoff with jitter
                print(f"Rate limited (429). Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
            elif response.status_code != 200:
                print(f"Error: Received status code {response.status_code} for page {start}")
                break
            else:
                success = True

                soup = BeautifulSoup(response.text, 'html.parser')
                items = soup.find_all('div', class_='gs_ri')

                print(f"Found {len(items)} articles on page {start // 10 + 1}")

                for item in items:
                    title_tag = item.find('h3', class_='gs_rt')
                    title = title_tag.get_text(strip=True) if title_tag else "N/A"

                    url_tag = item.find('h3', class_='gs_rt').find('a') if item.find('h3', class_='gs_rt') else None
                    url = url_tag['href'] if url_tag else "N/A"

                    author_tag = item.find('div', class_='gs_a')
                    author_text = author_tag.get_text(strip=True) if author_tag else "N/A"
                    authors = author_text.split(' - ')[0].strip() if ' - ' in author_text else author_text

                    year_tag = item.find('span', class_='gs_fl')
                    year = year_tag.get_text(strip=True).split(' ')[-1].strip() if year_tag else "N/A"

                    results.append({
                        'Title': title,
                        'Author': authors,
                        'Year': year,
                        'URL': url
                    })

                time.sleep(5 + random.uniform(0, 2))  # Randomized delay to avoid detection

    print(f"Total articles collected: {len(results)}")
    return results

def save_to_csv(results, filename='articles.csv'):
    df = pd.DataFrame(results)
    df.to_csv(filename, index=False)
    print(f"Results saved to {filename}")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Web scrape articles from Google Scholar')
    parser.add_argument('query', type=str, help='Search query for Google Scholar')
    parser.add_argument('-n', type=int, default=10, help='Number of articles to scrape (default: 10)')
    args = parser.parse_args()

    results = search_google_scholar(args.query, args.n)
    save_to_csv(results)
