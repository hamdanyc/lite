#!/bin/bash

# Create pdf directory if it doesn't exist
# mkdir -p pdf

# Read URLs from src.txt
count=1
while IFS= read -r url; do
    # Skip the first line (header)
    if [ $count -gt 1 ]; then
        # Extract filename from URL
        filename=$(echo "$url" | awk -F'/' '{print $NF}')
        
        # If filename is empty, use default name
        if [ -z "$filename" ]; then
            filename="document_$count"
        fi
        
        # Sanitize filename by removing special characters
        filename=$(echo "$filename" | tr '/:*\?%=' '-')
        
        # Ensure the filename has a .pdf extension
        if [[ "$filename" != *.pdf ]]; then
            filename="$filename.pdf"
        fi
        
        # Download the file
        echo "Downloading $url to pdf/$filename"
        curl -o "pdf/$filename" "$url"
    fi
    
    ((count++))
done < src.txt

echo "All downloads completed."
