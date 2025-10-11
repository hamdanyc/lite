import requests
import os
import csv
import json
import re  # Added missing import for regular expressions
from tqdm import tqdm

# Create pdf directory if it doesn't exist
pdf_dir = 'pdf'
if not os.path.exists(pdf_dir):
    os.makedirs(pdf_dir)
else:
    # Remove all existing files in pdf directory
    for filename in os.listdir(pdf_dir):
        file_path = os.path.join(pdf_dir, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")

# Create error log file
error_log = []

# Read URLs from CSV file
with open('articles.csv', newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    total_articles = sum(1 for row in reader)
    csvfile.seek(0)
    
    downloaded_count = 0
    failed_count = 0
    
    # Create progress bar
    progress_bar = tqdm(total=total_articles, desc="Downloading", unit="file")
    
    for index, row in enumerate(reader, 1):
        url = row['URL']
        short_title = row['Short-Title']  # Use short_title from CSV
        
        try:
            # Use short_title from CSV as filename
            filename = f"{short_title}.pdf"
            
            # Convert to lowercase (small caps)
            filename = filename.lower()
            
            # Truncate to 63 characters (leaving space for .pdf extension)
            if len(filename) > 63:
                filename = filename[:60] + '.pdf'
            
            # Sanitize filename by removing special characters
            filename = re.sub(r'[<>:"/\\|?*]', '', filename)
            
            # Ensure the filename has a .pdf extension
            if not filename.endswith('.pdf'):
                filename += '.pdf'
            
            filename = os.path.join(pdf_dir, filename)
            
            # Download the PDF
            response = requests.get(url)
            response.raise_for_status()
            
            # Save the PDF file
            with open(filename, 'wb') as file:
                file.write(response.content)
            
            downloaded_count += 1
            progress_bar.update(1)
            
        except requests.exceptions.RequestException as e:
            failed_count += 1
            error_entry = {
                "url": url,
                "error": str(e),
                "filename": filename if 'filename' in locals() else "N/A"
            }
            error_log.append(error_entry)
            progress_bar.update(1)
    
    progress_bar.close()
    
    # Write errors to JSON file
    with open('error.json', 'w') as error_file:
        json.dump(error_log, error_file, indent=2)
    
    # Print summary
    print("\nDownload Summary:")
    print(f"Total articles processed: {total_articles}")
    print(f"Successfully downloaded: {downloaded_count}")
    print(f"Failed to download: {failed_count}")
    print("Errors saved to: error.json")
