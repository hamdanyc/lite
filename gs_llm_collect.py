import os
from chromadb import CloudClient
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
import json

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
    prompt = """Extract the title, author(s), publication, year of publication and the publisher from the text. 
Return the result in valid JSON format with the following keys: Title, Author, Publication, Year, Publisher.
If a field is not found, leave it as an empty string.
    
Example format:
{
  "Title": "Sample Title",
  "Author": "John Doe",
  "Publication": "Journal of Sample Research",
  "Year": "2023",
  "Publisher": "Sample Publisher"
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
                "Publisher": ""
            }
            
            for line in response_text.split('\n'):
                for key in metadata.keys():
                    if key in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            metadata[key] = parts[1].strip().strip('"')
                            break
            
            # Ensure all required keys are present
            for key in ["Title", "Author", "Publication", "Year", "Publisher"]:
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
            "Publisher": ""
        }

def main():
    # Load environment variables
    load_dotenv()
    
    # Initialize LLM
    llm = init_chat_model("llama-3.1-8b-instant", model_provider="groq")
    
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
                
            # Extract metadata from the text of the first page using LLM
            first_page_text = results['documents'][0]
            metadata = extract_metadata_with_llm(first_page_text, llm)
            
            # Check if all metadata fields are empty
            if all(value == "" for value in metadata.values()):
                print(f"No metadata found in first page of collection '{collection.name}'")
                continue
                
            # Update only the first page document with the new metadata
            for i in range(len(results['documents'])):
                # Create a new metadata dictionary with both existing and new metadata
                new_metadata = {
                    **results['metadatas'][i],
                    **metadata
                }
                
                # Update the document with the new metadata
                col.update(
                    documents=results['documents'][i],
                    metadatas=[new_metadata],
                    ids=results['ids'][i]
                )
            
            print(f"✅ Successfully updated metadata for {len(results['documents'])} documents in collection '{collection.name}'")
            
        except Exception as e:
            print(f"❌ Error processing collection '{collection.name}': {str(e)}")
            continue

if __name__ == "__main__":
    main()
