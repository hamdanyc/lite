import os
import pandas as pd
from bs4 import BeautifulSoup

def process_html_files(directory):
    results = []
    
    # Get all HTML files in the directory
    html_files = [f for f in os.listdir(directory) if f.endswith('.html')]
    
    for filename in html_files:
        file_path = os.path.join(directory, filename)
        
        with open(file_path, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
            items = soup.find_all('div', class_='gs_ri')
            
            print(f"Processing {filename}: Found {len(items)} articles")
            
            for item in items:
                title_tag = item.find('h3', class_='gs_rt')
                title = title_tag.get_text(strip=True) if title_tag else "N/A"

                url_tag = item.find('a', href=True) if item.find('a', href=True) else None
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
    
    return results

def save_to_csv(results, filename='articles.csv'):
    df = pd.DataFrame(results)
    df.to_csv(filename, index=False)
    print(f"Results saved to {filename}")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Process Google Scholar HTML files')
    parser.add_argument('directory', type=str, help='Directory containing Google Scholar HTML pages')
    parser.add_argument('-o', '--output', type=str, default='articles.csv', 
                        help='Output CSV filename (default: articles.csv)')
    args = parser.parse_args()

    print(f"Reading HTML files from {args.directory}...")
    results = process_html_files(args.directory)
    save_to_csv(results, args.output)
