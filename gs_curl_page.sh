#!/bin/bash

# Create pages directory if it doesn't exist
mkdir -p pages

# Base URL without the start parameter
base_url="https://scholar.google.com/scholar"
params="&q=chatgpt+student+learning+psychology&hl=en&as_sdt=0,5"

# Start value and increment
start=10
increment=10

# Counter for output files
counter=1

# Fetch 10 pages (you can adjust this number as needed)
for ((i=0; i<10; i++))
do
    # Construct the full URL
    url="${base_url}?start=${start}${params}"
    
    # Output file
    output_file="pages/${counter}.html"
    
    # Use curl to fetch the page with headers to mimic a browser and follow redirects
    echo "Fetching $url and saving to $output_file"
    curl -s -L -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36" "$url" > "$output_file"
    
    # Check if we got a 302 redirect in the file
    if grep -q "302 Moved" "$output_file"; then
        echo "Received 302 redirect for $url"
        # You might want to add additional handling here, like solving CAPTCHA
        # or adding more sophisticated headers/user agents
    fi
    
    # Increment values for next iteration
    start=$((start + increment))
    counter=$((counter + 1))
    
    # Be respectful to the server - add a delay between requests
    sleep 5
done

echo "Finished fetching pages"
