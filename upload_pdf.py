import os
from PyPDF2 import PdfReader
from chromadb import CloudClient
from dotenv import load_dotenv

def process_pdf(pdf_path):
    """Convert PDF to text with metadata"""
    try:
        reader = PdfReader(pdf_path)
        documents = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            metadata = {
                "page_number": i + 1,
                "word_count": len(text.split()) if text else 0,
                "source_file": os.path.basename(pdf_path)
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
    
    # Process each PDF file
    for idx, pdf_file in enumerate(pdf_files, 1):
        pdf_path = os.path.join(pdf_dir, pdf_file)
        print(f"\nProcessing {pdf_file} ({idx}/{len(pdf_files)})")
        
        try:
            # Process PDF
            documents = process_pdf(pdf_path)
            
            if not documents:
                print(f"No documents extracted from {pdf_file}")
                continue
                
            # Create collection name from file name
            collection_name = os.path.splitext(pdf_file)[0]
            
            # Get or create collection
            collection = client.get_or_create_collection(name=collection_name)
            
            # Add documents to collection
            for doc in documents:
                collection.add(
                    documents=doc["text"],
                    metadatas=doc["metadata"],
                    ids=f"{collection_name}_page_{doc['metadata']['page_number']}"
                )
                
            print(f"✅ Successfully uploaded {len(documents)} pages from {pdf_file}")
            
        except Exception as e:
            print(f"❌ Error uploading {pdf_file}: {str(e)}")
            continue

if __name__ == "__main__":
    main()
