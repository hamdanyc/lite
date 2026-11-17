import os
import json
import time
from PyPDF2 import PdfReader
from chromadb import CloudClient
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

def init_chat_model(model_name, model_provider):
    """Initialize chat model based on provider"""
    if model_provider == "groq":
        return ChatGroq(
            model_name=model_name,
            temperature=0,
            max_tokens=1000
        )
    else:
        raise ValueError(f"Unsupported model provider: {model_provider}")

def extract_metadata_with_llm(text, llm):
    """Extract metadata using LLM with improved JSON handling"""
    prompt = """Extract the title, author(s), publication, year of publication, abstract and the publisher from the text. 
Return the result in valid JSON format with the following keys: Title, Author, Publication, Year, Publisher and Abstract.
If a field is not found, leave it as an empty string.
    
Example format:
{
  "Title": "Sample Title",
  "Author": "John Doe",
  "Publication": "Journal of Sample Research",
  "Year": "2023",
  "Publisher": "Sample Publisher"
  "Abstract": "Abstract text"
}"""

    # Create message
    message = HumanMessage(content=prompt + "\n\n" + text)
    
    try:
        # Get response from LLM
        response = llm.invoke([message])
        response_text = response.content
        
        # Try to parse JSON response
        try:
            metadata = json.loads(response_text)
        except json.JSONDecodeError:
            # Fallback to basic parsing if JSON parsing fails
            metadata = {
                "Title": "",
                "Author": "",
                "Publication": "",
                "Year": "",
                "Publisher": "",
                "Abstract": ""
            }
            
            for line in response_text.split('\n'):
                for key in metadata.keys():
                    if key in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            metadata[key] = parts[1].strip().strip('"')
                            break
            
            # Ensure all required keys are present
            for key in ["Title", "Author", "Publication", "Year", "Publisher", "Abstract"]:
                if key not in metadata:
                    metadata[key] = ""
        
        return metadata
    
    except Exception as e:
        print(f"Error extracting metadata with LLM: {str(e)}")
        return {
            "Title": "",
            "Author": "",
            "Publication": "",
            "Year": "",
            "Publisher": "",
            "Abstract": ""
        }

def process_pdf(pdf_path):
    """Convert PDF to text with metadata"""

    # Initialize LLM
    llm = init_chat_model("llama-3.1-8b-instant", model_provider="groq")
    
    try:
        reader = PdfReader(pdf_path)
        documents = []
        for i, page in enumerate(reader.pages):
            metadatas = {}
            text = page.extract_text()
            if i == 0:
                metadatas = extract_metadata_with_llm(text, llm)
            metadata = {
                "page_number": i + 1,
                "word_count": len(text.split()) if text else 0,
                "source_file": os.path.basename(pdf_path),
                **metadatas
            }
            documents.append({
                "text": text,
                "metadata": metadata
            })
        return documents
    except Exception as e:
        print(f"Error processing {pdf_path}: {str(e)}")
        return []

def main():
    # Load environment variables
    load_dotenv()

    # Get Chroma Cloud credentials
    ch_api_key = os.getenv('CHROMA_API_KEY')
    ch_tenant = os.getenv('CHROMA_TENANT')
    ch_database = os.getenv('CHROMA_DATABASE')
    
    if not all([ch_api_key, ch_tenant, ch_database]):
        raise ValueError("Missing Chroma Cloud credentials in environment variables")
    
    # Initialize Chroma Cloud client
    client = CloudClient(
        tenant=ch_tenant,
        database=ch_database,
        api_key=ch_api_key
    )
    
    # Get all PDF files in the pdf directory
    pdf_dir = "pdf"
    pdf_files = [f for f in os.listdir(pdf_dir) if f.endswith('.pdf')]
    
    print(f"Found {len(pdf_files)} PDF files to process")
    
    # Initialize counters and error log
    success_count = 0
    fail_count = 0
    error_log = []
    
    # Process each PDF file with progress bar
    for idx, pdf_file in enumerate(pdf_files, 1):
        pdf_path = os.path.join(pdf_dir, pdf_file)
        print(f"\nProcessing {pdf_file} ({idx}/{len(pdf_files)})")
        
        try:
            # Process PDF
            documents = process_pdf(pdf_path)
            
            if not documents:
                print(f"No documents extracted from {pdf_file}")
                fail_count += 1
                continue
                
            # Create collection name from file name
            collection_name = os.path.splitext(pdf_file)[0]
            
            # Check if collection exists
            existing_collections = client.list_collections()
            if collection_name in [col.name for col in existing_collections]:
                print(f"Collection '{collection_name}' already exists. Skipping...")
                fail_count += 1
                continue
                
            # Create new collection
            collection = client.create_collection(name=collection_name)
            
            # Add documents to collection
            for doc in documents:
                collection.add(
                    documents=doc["text"],
                    metadatas=doc["metadata"],
                    ids=f"{collection_name}_page_{doc['metadata']['page_number']}"
                )
                
            print(f"✅ Successfully uploaded {len(documents)} pages to new collection '{collection_name}'")
            success_count += 1
            
        except Exception as e:
            error_message = str(e)
            print(f"❌ Error uploading {pdf_file}: {error_message}")
            error_log.append({
                "pdf_file": pdf_file,
                "error_message": error_message
            })
            fail_count += 1
            continue
        
        # Update progress bar
        progress = (idx / len(pdf_files)) * 100
        bar_length = 50
        filled_length = int(bar_length * idx // len(pdf_files))
        bar = '█' * filled_length + '-' * (bar_length - filled_length)
        print(f"\rProgress: |{bar}| {progress:.1f}% Complete", end='', flush=True)
        time.sleep(0.1)  # Small delay to allow progress bar to update
    
    # Save error log to file
    with open('upload.json', 'w') as f:
        json.dump(error_log, f, indent=2)
    print("\n\nError log saved to upload.json")
    
    # Display final statistics
    print(f"\n\n✅ Successfully uploaded: {success_count} PDF files")
    print(f"❌ Failed to upload: {fail_count} PDF files")
    print(f"Total processed: {success_count + fail_count} PDF files")

if __name__ == "__main__":
    main()
