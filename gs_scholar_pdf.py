import requests
import os
import csv
import re

# Create pdf directory if it doesn't exist
if not os.path.exists('pdf'):
    os.makedirs('pdf')

# Read URLs from CSV file
with open('articles.csv', newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        url = row['URL']
        try:
            # Get the filename from the URL
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
            
            print(f"Successfully downloaded {filename}")
        
        except requests.exceptions.RequestException as e:
            print(f"Error downloading {url}: {e}")
