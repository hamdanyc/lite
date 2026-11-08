## Purpose

a Python script that follows the steps for analyzing ethnic conflict factors. This script includes reading an XML codebook, using the Groq API to extract semantic phrases, searching through HTML articles, and counting occurrences of those phrases.

Generate a Python script to analyze ethnic conflict factors using these steps:

## Steps
1. Read codebook.qdc as XML and extract all <Code> elements
2. Use Groq API (model: openai/gpt-oss-20b) to get multi-word semantic phrases for factors (minimum 2 words)
3. For each factor/sub-factor, search all HTML articles in resource/Articles
4. Scan article batches against all factor/sub-factor descriptions, have the LLM return exact source phrases that express each factor, verify those phrases occur in the article, and count each non-overlapping phrase occurrence once.
5. Store results as list of dicts with fields: factor, semantic_phrases, count
6. Present results in structure:
   factor | semantic_phrases | count
   (Example: "Historical & Emotional Drivers" | "past grievances, ethnic trauma" | 15)

## Guidelines:
   - Add .env validation for API key
   - Implement robust error handling
   - Use pathlib for path operations
   - create requirements.txt for dependencies
   - Add unit tests
   - Use logging for debugging and tracking progress.
   - set max_files = 25 for files to process. Default all files.
   - bash to execute the script with optional argument for number of files to process.
   - scan one-article/all-codes at a time to avoid overwhelming the API.
   - write results to a markdown file named conflict_analysis_results.md in the current working directory.

