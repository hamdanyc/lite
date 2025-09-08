import os
import json
import sys
import re

def count_keywords(text, keywords):
    """
    Count occurrences of each keyword in the text using regex.
    
    Args:
        text (str): Text to search
        keywords (list): List of keywords to count
    
    Returns:
        dict: Dictionary mapping keywords to their counts
    """
    counts = {}
    for keyword in keywords:
        # Use case-insensitive matching with word boundaries
        pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
        matches = re.findall(pattern, text)
        counts[keyword] = len(matches)
    return counts

def main():
    all_keywords = set()
    """
    Main function to execute the keyword counting analysis.
    Usage: python multi_collection_ca.py <input_file> <output_file>
    """
    if len(sys.argv) != 3:
        print("Usage: python multi_collection_ca.py <input_file> <output_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    # Validate input file exists
    if not os.path.isfile(input_file):
        print(f"Input file {input_file} not found")
        sys.exit(1)

    try:
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as file:
            lines = file.readlines()
    except Exception as e:
        print(f"Error reading input file: {str(e)}")
        sys.exit(1)

    # Find the keywords line
    keywords_found = False
    for line in lines:
        if '**Keyword(s)**' in line:
            keywords_found = True
            # Parse keywords
            try:
                # Split the line and extract keywords
                keyword_part = line.split(':', 1)[1]
                words = [word.strip().lower() for word in keyword_part.split(',') if word.strip()]
                all_keywords.update(words)
                print(f'Found keywords: {words}')
            except Exception as e:
                print(f"Error parsing keywords: {str(e)}")
                sys.exit(1)

    if not keywords_found:
        print("No '**Keywords**' line found in the input file.")
        sys.exit(1)

    # Read input file content for keyword counting
    try:
        with open(input_file, 'r', encoding='utf-8', errors='ignore') as file:
            text = file.read().lower()
    except Exception as e:
        print(f"Error reading input file content: {str(e)}")
        sys.exit(1)

    if not text:
        print(f"No text content found in input file '{input_file}'. " +
              "Make sure the file contains valid content.")
        sys.exit(1)

    # Count keywords
    keyword_counts = count_keywords(text, list(all_keywords))

    # Write results to output file
    try:
        with open(output_file, 'w', encoding='utf-8') as json_file:
            json.dump(keyword_counts, json_file, indent=4)
        print(f"Keyword counts saved to {output_file}")
    except Exception as e:
        print(f"Error writing output file: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main()
