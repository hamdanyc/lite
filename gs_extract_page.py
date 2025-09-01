import os
import pandas as pd
from bs4 import BeautifulSoup

def process_html_files(directory):
    results = []
    
    # Get all HTML files in the directory
    html_files = [f for f in os.listdir(directory) if f.endswith('.html')]
    
    # Open url.txt for writing
    with open('url.txt', 'w', encoding='utf-8') as url_file:
        for filename in html_files:
            file_path = os.path.join(directory, filename)
            
            with open(file_path, 'r', encoding='utf-8') as file:
                soup = BeautifulSoup(file, 'html.parser')
                items = soup.find_all('div', class_='gs_r gs_or gs_scl')
                
                print(f"Processing {filename}: Found {len(items)} articles")
                
                for item in items:
                    title_tag = item.find('h3', class_='gs_rt')
                    title = title_tag.get_text(strip=True) if title_tag else "N/A"

                    # Use multiple strategies to find PDF links
                    url_tag = None
                    
                    # Strategy 1: Look for the PDF div with [PDF] link
                    pdf_div = item.find('div', class_='gs_or_ggsm')
                    if pdf_div:
                        print("Found PDF div")
                        # Try to find a link with PDF in the text
                        pdf_link = pdf_div.find('a', text=lambda t: t and '[PDF]' in t)
                        if pdf_link:
                            print("Found PDF link by text")
                            url_tag = pdf_link
                        else:
                            # If that fails, just get any link
                            url_tag = pdf_div.find('a', href=True)
                            if url_tag:
                                print(f"Found link by href: {url_tag['href']}")
                    else:
                        print("No PDF div found")
                        # Strategy 2: If we couldn't find the PDF div, try finding any link in the item
                        url_tag = item.find('a', href=True)
                    
                    # Only use the URL if it's a PDF link
                    url = url_tag['href'] if url_tag or 'href' in url_tag or url_tag['href'].endswith('.pdf') else "N/A"

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
                    
                    # Write URL to url.txt
                    if url_tag != "N/A":
                        url_file.write(url + '\n')
    
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
