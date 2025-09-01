#!/bin/bash

# Create the pdf directory if it doesn't exist
mkdir -p pdf

# Remove all existing files in the pdf directory
# rm -f pdf/*

# Read each URL from src.txt and download it if it ends with .pdf
total_urls=$(wc -l < url.txt)
count=0
success=0
failed=0

echo "Starting PDF download process..."

while IFS= read -r url; do
    # Check if the URL ends with .pdf
    if [[ "$url" == *.pdf ]]; then
        count=$((count + 1))
        echo -e "\nProcessing URL $count of $total_urls: $url"
        
        # Extract the filename from the URL
        filename=$(basename "$url")
        
        # If filename is empty (e.g., URL ends with a slash), use a default name
        if [[ -z "$filename" ]]; then
            filename="index.html"
        fi

        # Download the URL and save it to the pdf directory
        echo "Downloading..."
        if curl -s -o "pdf/$filename" "$url"; then
            echo "Saved: pdf/$filename"
            success=$((success + 1))
        else
            echo "Failed to download: $url"
            failed=$((failed + 1))
        fi
    fi
done < url.txt

echo -e "\nDownload complete!"
echo "Total URLs processed: $count"
echo "Successfully downloaded: $success"
echo "Failed to download: $failed"
