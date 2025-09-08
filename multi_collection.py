import os
import json
from collections import Counter

def extract_keywords(text):
    """Extract keywords from text with frequency count
    
    Parameters:
        text (str): Text to analyze
        
    Returns:
        dict: Dictionary of keywords
    """
    # Convert to lowercase for case-insensitive counting
    words = text.lower().split()
    
    # Filter out common words
    filtered_words = [word for word in words if len(word) > 3]
    
    return dict(Counter(filtered_words))

def extract_keywords_with_count(text):
    """Extract keywords with count
    
    Parameters:
        text: Text to analyze
    
    Returns:
        dict: Dictionary of keywords and counts
    """
    # Count keyword frequencies
    # Return keywords with their respective frequencies
    return dict(Counter(text.split()))
