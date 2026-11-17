import os
from chromadb import CloudClient
from dotenv import load_dotenv

def extract_metadata_from_text(text):
    """Extract metadata from text content"""
    # Simple text parsing for metadata (this would need to be customized based on actual content)
    metadata = {
        "Publication": "",
        "Year": "",
        "Publisher": "",
        "Title": "",
        "Author": ""
    }
    
    # This is a basic example - you would need to implement actual parsing logic
    # based on how the metadata appears in your text
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    for line in lines:
        if line.lower().startswith("publication:"):
            metadata["Publication"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("year:"):
            metadata["Year"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("publisher:"):
            metadata["Publisher"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("title:"):
            metadata["Title"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("author:"):
            metadata["Author"] = line.split(":", 1)[1].strip()
    
    return metadata

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
    
    # Get all collections
    collections = client.list_collections()
    
    print(f"Found {len(collections)} collections to process")
    
    for idx, collection in enumerate(collections, 1):
        print(f"\nProcessing collection '{collection.name}' ({idx}/{len(collections)})")
        
        try:
            # Get the first page (page_number = 1) document
            col = client.get_collection(name=collection.name)
            results = col.get(where={"page_number": 1})
            
            if not results['documents']:
                print(f"No documents found in collection '{collection.name}'")
                continue
                
            # Extract metadata from the text of the first page
            first_page_text = results['documents'][0]
            metadata = extract_metadata_from_text(first_page_text)
            
            if not any(metadata.values()):
                print(f"No metadata found in first page of collection '{collection.name}'")
                continue
                
            # Update all documents with the new metadata
            all_results = col.get()
            
            for i in range(len(all_results['documents'])):
                # Create a new metadata dictionary with both existing and new metadata
                new_metadata = {
                    **all_results['metadatas'][i],
                    **metadata
                }
                
                # Update the document with the new metadata
                col.update(
                    documents=all_results['documents'][i],
                    metadatas=[new_metadata],
                    ids=all_results['ids'][i]
                )
            
            print(f"✅ Successfully updated metadata for {len(all_results['documents'])} documents in collection '{collection.name}'")
            
        except Exception as e:
            print(f"❌ Error processing collection '{collection.name}': {str(e)}")
            continue

if __name__ == "__main__":
    main()
