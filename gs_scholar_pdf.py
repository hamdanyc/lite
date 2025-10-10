import requests
import os
import csv
import re
import json

def generate_short_title(title):
    """Simulated LLM function to generate a short title (max 15 chars)"""
    # In a real implementation, this would call an LLM API
    # For this example, we'll just take the first 15 characters
    if not title:
        return "dl"
    
    # Remove any non-alphanumeric characters and spaces
    clean_title = re.sub(r'[^a-zA-Z0-9\s]', '', title)
    
    # Split by spaces and take first 2-3 words (max 15 chars)
    words = clean_title.split()
    short_title = ""
    
    for word in words:
        if len(short_title) + len(word) + 1 <= 15:
            short_title = short_title + ("-" if short_title else "") + word
        else:
            break
    
    return short_title if short_title else "dl"

# Create pdf directory if it doesn't exist
if not os.path.exists('pdf'):
    os.makedirs('pdf')

# Create error log file
error_log = []

# Read URLs from CSV file
with open('articles.csv', newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    total_articles = sum(1 for row in reader)
    csvfile.seek(0)
    
    downloaded_count = 0
    failed_count = 0
    
    for index, row in enumerate(reader, 1):
        url = row['URL']
        title = row.get('Title', '')
        
        try:
            # Generate short title using LLM (simulated here)
            short_title = generate_short_title(title)
            
            # Use Title from CSV as filename if available, otherwise use URL
            if title:
                filename = f"{short_title}-{title}.pdf"
            else:
                filename = url.split('/')[-1]
            
            # If filename is empty (URL ends with /), use a default name
            if not filename:
                filename = 'downloaded_file.pdf'
            
            # Sanitize filename by removing special characters
            filename = re.sub(r'[<>:"/\\|?*]', '', filename)
            
            # Ensure the filename has a .pdf extension
            if not filename.endswith('.pdf'):
                filename += '.pdf'
            
            filename = os.path.join('pdf', filename)
            
            # Download the PDF
            response = requests.get(url)
            response.raise_for_status()
            
            # Save the PDF file
            with open(filename, 'wb') as file:
                file.write(response.content)
            
            downloaded_count += 1
            print(f"({index}/{total_articles}) Successfully downloaded {filename}")
        
        except requests.exceptions.RequestException as e:
            failed_count += 1
            error_entry = {
                "url": url,
                "error": str(e),
                "filename": filename if 'filename' in locals() else "N/A"
            }
            error_log.append(error_entry)
            print(f"({index}/{total_articles}) Error downloading {url}: {e}")
    
    # Write errors to JSON file
    with open('error.json', 'w') as error_file:
        json.dump(error_log, error_file, indent=2)
    
    # Print summary
    print("\nDownload Summary:")
    print(f"Total articles processed: {total_articles}")
    print(f"Successfully downloaded: {downloaded_count}")
    print(f"Failed to download: {failed_count}")
    print("Errors saved to: error.json")
