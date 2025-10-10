import os
import pandas as pd
import re
from bs4 import BeautifulSoup
from groq import Groq
import sys

def generate_short_title(title):
    """Use LLM to generate a short title (8-10 words with hyphens)"""
    if not title or len(title.split()) <= 10:
        return title
    
    client = Groq()
    prompt = f"Shorten this title to 8-10 words with hyphens as separators, removing any [PDF] or [HTML] markers: {title}"
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a title shortener. Create concise titles with 8-10 words separated by hyphens."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=50,
        top_p=1,
        stream=False,
    )
    
    short_title = response.choices[0].message.content.strip()
    
    # Remove any [PDF] or [HTML] markers from the short title
    short_title = short_title.replace("[PDF]", "").replace("[HTML]", "").strip()
    
    # Ensure the short title is not empty and has 8-10 words
    if not short_title or len(short_title.split('-')) < 8 or len(short_title.split('-')) > 10:
        # Fallback: create a short title by taking first 10 words with hyphens
        words = title.split()[:10]
        short_title = '-'.join(words)
        if len(short_title) > 100:  # Safety check for very long titles
            short_title = '-'.join(words[:8])
    
    return short_title

def process_html_files(directory):
    results = []
    
    # Get all HTML files in the directory
    html_files = [f for f in os.listdir(directory) if f.endswith('.html')]
    total_files = len(html_files)
    
    # Open url.txt for writing
    with open('url.txt', 'w', encoding='utf-8') as url_file:
        for i, filename in enumerate(html_files, 1):
            file_path = os.path.join(directory, filename)
            
            with open(file_path, 'r', encoding='utf-8') as file:
                soup = BeautifulSoup(file, 'html.parser')
                items = soup.find_all('div', class_='gs_r gs_or gs_scl')
                
                # Progress bar display
                progress = int((i / total_files) * 100)
                bar_length = 50
                filled_length = int(bar_length * i // total_files)
                bar = '█' * filled_length + '-' * (bar_length - filled_length)
                sys.stdout.write(f'\rProcessing files: |{bar}| {progress}% ({i}/{total_files})')
                sys.stdout.flush()
                
                for j, item in enumerate(items, 1):
                    title_tag = item.find('h3', class_='gs_rt')
                    title = title_tag.get_text(strip=True, separator=" ") if title_tag else "N/A"
                    
                    # Remove [PDF] and [HTML] markers from the title before shortening
                    title = title.replace("[PDF]", "").replace("[HTML]", "").strip()
                    
                    # Generate short title using LLM
                    short_title = generate_short_title(title)
                    
                    # Use multiple strategies to find PDF links
                    url_tag = None
                    
                    # Strategy 1: Look for the PDF div with [PDF] link
                    pdf_div = item.find('div', class_='gs_or_ggsm')
                    if pdf_div:
                        # print("Found PDF div")
                        # Try to find a link with PDF in the text
                        pdf_link = pdf_div.find('a', string=lambda t: t and '[PDF]' in t)
                        if pdf_link:
                            # print("Found PDF link by text")
                            url_tag = pdf_link
                        else:
                            # If that fails, just get any link
                            url_tag = pdf_div.find('a', href=True)
                            if url_tag:
                                # print(f"Found link by href: {url_tag['href']}")
                                pass
                    else:
                        # print("No PDF div found")
                        # Strategy 2: If we couldn't find the PDF div, try finding any link in the item
                        url_tag = item.find('a', href=True)
                        if url_tag:
                            # print(f"Found fallback link: {url_tag['href']}")
                            pass
                        else:
                            # print("No link found in item")
                            pass
                    
                    # Use any URL found, not just PDF links
                    url = url_tag['href'] if url_tag or 'href' in url_tag else "N/A"
                    # print(f"Final URL: {url}")

                    author_tag = item.find('div', class_='gs_a')
                    author_text = author_tag.get_text(strip=True) if author_tag else "N/A"
                    
                    # Extract year from author text
                    year = "N/A"
                    if author_text:
                        # Look for year in parentheses or at the end
                        year_match = re.search(r'(\d{4})', author_text)
                        if year_match:
                            year = year_match.group(1)
                        else:
                            # Try to extract year from URL if present
                            if url != "N/A":
                                year_match = re.search(r'/(\d{4})/', url)
                                if year_match:
                                    year = year_match.group(1)
                    
                    authors = author_text.split(' - ')[0].strip() if ' - ' in author_text else author_text
                    
                    results.append({
                        'Title': title,
                        'Short Title': short_title,
                        'Author': authors,
                        'Year': year,
                        'URL': url
                    })
                    
                    # Write URL to url.txt
                    if url != "N/A":
                        url_file.write(url + '\n')
    
    return results

def save_to_csv(results, filename='articles.csv'):
    df = pd.DataFrame(results)
    df.to_csv(filename, index=False)
    print(f"\nResults saved to {filename}")

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
