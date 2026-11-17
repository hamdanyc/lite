import os
import json
import argparse
import time
import re
from pathlib import Path
import yaml
from chromadb import CloudClient
from chromadb.api.models import Collection
from PyPDF2 import PdfReader
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate

# Initialize LLM
llm = ChatGroq(model_name="openai/gpt-oss-20b", temperature=0)

def init_chroma_client(database="machine_learning"):
    """Initialize Chroma Cloud client from a named profile in .config.yml."""
    config_path = Path(__file__).with_name(".config.yml")
    with config_path.open("r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}

    try:
        chromadb_config = config["chromadb"]
        database_config = chromadb_config["databases"][database]
    except (KeyError, TypeError):
        raise ValueError(
            f"Chroma database profile '{database}' not found in {config_path}"
        ) from None

    if not chromadb_config.get("tenant"):
        raise ValueError(f"Chroma config is missing the shared tenant in {config_path}")

    required_fields = ("api_key", "database")
    missing_fields = [field for field in required_fields if not database_config.get(field)]
    if missing_fields:
        raise ValueError(
            f"Chroma database profile '{database}' is missing: {', '.join(missing_fields)}"
        )

    return CloudClient(
        tenant=chromadb_config["tenant"],
        database=database_config["database"],
        api_key=database_config["api_key"]
    )

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

def batch_process_pdfs(pdf_dir, collection_prefix="chroma_batch_"):
    """Batch process PDFs and upload to Chroma"""
    client = init_chroma_client()
    
    # Get all PDF files in the directory
    pdf_files = [f for f in os.listdir(pdf_dir) if f.endswith('.pdf')]
    
    print(f"Found {len(pdf_files)} PDF files to process")
    
    # Initialize counters and error log
    success_count = 0
    fail_count = 0
    error_log = []
    
    # Process each PDF file
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
            collection_name = f"{collection_prefix}{os.path.splitext(pdf_file)[0]}"
            
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
    if error_log:
        error_log_path = f"chroma_errors_{int(time.time())}.json"
        with open(error_log_path, 'w') as f:
            json.dump(error_log, f, indent=2)
        print(f"\nError log saved to {error_log_path}")
    
    print(f"\nBatch processing complete: {success_count} successful, {fail_count} failed")
    return success_count, fail_count

def bulk_update_metadata(collection_name, update_criteria):
    """Bulk update metadata for documents in a collection"""
    client = init_chroma_client()
    
    try:
        collection = client.get_collection(name=collection_name)
        results = collection.get()
        
        if not results['documents']:
            print(f"No documents found in collection '{collection_name}'")
            return 0
        
        updated_count = 0
        
        for i in range(len(results['documents'])):
            # Create a new metadata dictionary with both existing and new metadata
            new_metadata = {
                **results['metadatas'][i],
                **update_criteria
            }
            
            # Update the document with the new metadata
            collection.update(
                documents=results['documents'][i],
                metadatas=[new_metadata],
                ids=results['ids'][i]
            )
            
            updated_count += 1
        
        print(f"✅ Successfully updated metadata for {updated_count} documents in collection '{collection_name}'")
        return updated_count
        
    except Exception as e:
        print(f"❌ Error updating metadata in collection '{collection_name}': {str(e)}")
        return 0

def export_collection_data(collection_name, output_file):
    """Export all data from a collection to a file"""
    client = init_chroma_client()
    
    try:
        collection = client.get_collection(name=collection_name)
        results = collection.get()
        
        export_data = {
            "collection_name": collection_name,
            "documents": results['documents'],
            "metadatas": results['metadatas'],
            "ids": results['ids']
        }
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✅ Successfully exported collection '{collection_name}' to {output_file}")
        return True
        
    except Exception as e:
        print(f"❌ Error exporting collection '{collection_name}': {str(e)}")
        return False

def import_collection_data(input_file, collection_name=None):
    """Import data from a file into a collection"""
    client = init_chroma_client()
    
    try:
        with open(input_file, 'r') as f:
            import_data = json.load(f)
        
        # Use collection name from file if not provided
        if collection_name is None:
            collection_name = import_data.get("collection_name", f"imported_{int(time.time())}")
        
        # Check if collection exists
        existing_collections = client.list_collections()
        if collection_name in [col.name for col in existing_collections]:
            print(f"Collection '{collection_name}' already exists. Skipping...")
            return False
        
        # Create new collection
        collection = client.create_collection(name=collection_name)
        
        # Add documents to collection
        collection.add(
            documents=import_data["documents"],
            metadatas=import_data["metadatas"],
            ids=import_data["ids"]
        )
        
        print(f"✅ Successfully imported data into new collection '{collection_name}'")
        return True
        
    except Exception as e:
        print(f"❌ Error importing data into collection: {str(e)}")
        return False

def list_collections():
    """List all collections in Chroma"""
    client = init_chroma_client()
    
    try:
        collections = sorted(
            client.list_collections(),
            key=lambda collection: tuple(
                (1, int(part)) if part.isdigit() else (0, part.casefold())
                for part in re.split(r"(\d+)", collection.name)
            ),
        )
        
        print(f"Found {len(collections)} collections:")
        for i, collection in enumerate(collections, 1):
            print(f"{i}. {collection.name}")
        
        return collections
        
    except Exception as e:
        print(f"❌ Error listing collections: {str(e)}")
        return []

def delete_collection(collection_name):
    """Delete a collection from Chroma"""
    client = init_chroma_client()
    
    try:
        client.delete_collection(name=collection_name)
        print(f"✅ Successfully deleted collection '{collection_name}'")
        return True
        
    except Exception as e:
        print(f"❌ Error deleting collection '{collection_name}': {str(e)}")
        return False

def search_collections(query, n_results=5, output_file="search_results.md"):
    """Search across all collections"""
    client = init_chroma_client()
    
    try:
        # Get all collection names
        collections = client.list_collections()
        collection_names = [collection.name for collection in collections]
        
        # Query each collection
        all_results = []
        for collection_name in collection_names:
            collection = client.get_collection(name=collection_name)
            results = collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            for i, doc in enumerate(results['documents'][0]):
                all_results.append({
                    'collection': collection_name,
                    'document': doc,
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i]
                })
        
        # Sort by distance (relevance)
        all_results.sort(key=lambda x: x['distance'])
        
        print(f"Found {len(all_results)} results across {len(collection_names)} collections")
        
        # Write results to file
        with open(output_file, 'w') as f:
            f.write("# Search Results\n\n")
            f.write(f"Query: {query}\n")
            f.write(f"Total Results: {len(all_results)}\n\n")
            
            for i, result in enumerate(all_results, 1):
                f.write(f"## Result {i}\n")
                f.write(f"**Collection:** {result['collection']}\n")
                f.write(f"**Distance:** {result['distance']}\n")
                f.write(f"**Document:**\n{result['document']}\n")
                f.write(f"**Metadata:**\n{json.dumps(result['metadata'], indent=2)}\n\n")
        
        return all_results
        
    except Exception as e:
        print(f"❌ Error searching collections: {str(e)}")
        return []

def main():
    """Main function for command line interface"""
    parser = argparse.ArgumentParser(description="Chroma Cloud Utilities")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Batch process PDFs
    pdf_parser = subparsers.add_parser("batch-process", help="Batch process PDFs and upload to Chroma")
    pdf_parser.add_argument("--pdf-dir", required=True, help="Directory containing PDF files")
    pdf_parser.add_argument("--prefix", default="chroma_batch_", help="Prefix for collection names")
    
    # Bulk update metadata
    update_parser = subparsers.add_parser("bulk-update", help="Bulk update metadata for documents in a collection")
    update_parser.add_argument("--collection", required=True, help="Collection name")
    update_parser.add_argument("--metadata", required=True, help="Metadata to update (JSON string)")
    
    # Export collection data
    export_parser = subparsers.add_parser("export", help="Export all data from a collection")
    export_parser.add_argument("--collection", required=True, help="Collection name")
    export_parser.add_argument("--output", required=True, help="Output file path")
    
    # Import collection data
    import_parser = subparsers.add_parser("import", help="Import data from a file into a collection")
    import_parser.add_argument("--input", required=True, help="Input file path")
    import_parser.add_argument("--collection", help="Collection name (optional)")
    
    # List collections
    list_parser = subparsers.add_parser("list", help="List all collections")
    
    # Delete collection
    delete_parser = subparsers.add_parser("delete", help="Delete a collection")
    delete_parser.add_argument("--collection", required=True, help="Collection name")
    
    # Search collections
    search_parser = subparsers.add_parser("search", help="Search across all collections")
    search_parser.add_argument("--query", required=True, help="Search query")
    search_parser.add_argument("--n-results", type=int, default=5, help="Number of results per collection")
    
    args = parser.parse_args()
    
    if args.command == "batch-process":
        batch_process_pdfs(args.pdf_dir, args.prefix)
    elif args.command == "bulk-update":
        try:
            metadata = json.loads(args.metadata)
            bulk_update_metadata(args.collection, metadata)
        except json.JSONDecodeError:
            print("❌ Error: Invalid JSON in --metadata argument")
    elif args.command == "export":
        export_collection_data(args.collection, args.output)
    elif args.command == "import":
        import_collection_data(args.input, args.collection)
    elif args.command == "list":
        list_collections()
    elif args.command == "delete":
        delete_collection(args.collection)
    elif args.command == "search":
        search_collections(args.query, args.n_results)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()