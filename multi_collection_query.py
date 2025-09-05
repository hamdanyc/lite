import os
from chromadb import CloudClient
from langchain_core.prompts import PromptTemplate
from langchain_groq import ChatGroq
from dotenv import load_dotenv
import tiktoken

def query_collection(chroma_client, collection_name, query_criteria):
    # Perform query on a single collection
    collection = chroma_client.get_collection(name=collection_name)
    found_docs = collection.query(
        query_texts=[query_criteria["text"]],
        n_results=query_criteria["n_results"]
    )
    # Create a list of documents with metadata
    results = []
    for i, doc in enumerate(found_docs['documents'][0]):
        results.append({
            'collection': collection_name,
            'document': doc,
            'metadata': found_docs['metadatas'][0][i]
        })
    return results

def prepare_retrieval_data(results):
    # Prepare formatted text for LLM with collection name context
    formatted_retrieval = ""
    for result in results:
        formatted_retrieval += f"Collection: {result['collection']}\n"
        formatted_retrieval += f"Document: {result['document']}\n"
        formatted_retrieval += f"Metadata: {result['metadata']}\n\n"
    return formatted_retrieval

def summarize_long_text(text, llm, encoder=tiktoken.get_encoding("cl100k_base")):
    # Calculate number of tokens in text
    tokens = encoder.encode(text)
    max_tokens = 7500  # 15KB / 1.25 (approx) tokens per char = 7500 tokens
    if len(tokens) < max_tokens:
        return text  # No need for summary
    
    # Estimate the target summary length (20% of the original)
    target_length = max(200, int(len(tokens) * 0.2))
    
    # Create a summarization chain
    summary_prompt = PromptTemplate.from_template(
        "Please summarize the following text in a concise manner (keep it under {token_limit} tokens):\n\n"
        "Document text:\n{text}\n\n"
        "Summary:"
    )
    
    chain = summary_prompt | llm
    
    # Add token limit to the prompt and invoke
    return chain.invoke({
        "text": text,
        "token_limit": target_length
    }).content

def chunk_retrieval_data(text, max_chunk_size=7500):
    # Split text into chunks to manage token limits
    encoder = tiktoken.get_encoding("cl100k_base")
    chunks = []
    current_chunk = ""
    
    # Split the text by paragraph (double newline) first
    paragraphs = text.split("\n\n")
    
    for paragraph in paragraphs:
        if not paragraph:
            continue
            
        # Check if adding this paragraph would exceed the limit
        if len(encoder.encode(current_chunk + paragraph + "\n\n")) > max_chunk_size:
            # Store current chunk and start new
            chunks.append(current_chunk)
            current_chunk = paragraph
        else:
            # Add to current chunk
            current_chunk += paragraph + "\n\n"
            
    # Add the final chunk
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks

def write_to_file(filename, content):
    # Write content to file
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Results written to {filename}")

def main():
    # Initialize ChromaDB client
    # Load environment variables
    load_dotenv()

    # Get Chroma Cloud credentials
    ch_api_key = os.getenv('CHROMA_API_KEY')
    ch_tenant = os.getenv('CHROMA_TENANT')
    ch_database = os.getenv('CHROMA_DATABASE')
    
    if not all([ch_api_key, ch_tenant, ch_database]):
        raise ValueError("Missing Chroma Cloud credentials in environment variables")
    
    # Initialize Chroma Cloud client
    chroma_client = CloudClient(
        tenant=ch_tenant,
        database=ch_database,
        api_key=ch_api_key
    )

    # Get all collection names from ChromaDB
    all_collections = chroma_client.list_collections()
    collection_names = [collection.name for collection in all_collections]
    
    # Query each collection one by one
    all_results = []
    query_criteria = {
        "text": "Find active records",
        "n_results": 5 
    }
    
    # Read all collections
    for collection_name in collection_names:  
        print(f"Querying collection: {collection_name}")
        results = query_collection(chroma_client, collection_name, query_criteria)
        all_results.extend(results)
    
    # Prepare retrieved data
    llm_retrieval_data = prepare_retrieval_data(all_results)
    
    # Initialize LLM
    llm = ChatGroq(temperature=0, model_name="llama-3.1-8b-instant")
    
    # Token management for input text
    # 1. Split data into chunks
    chunks = chunk_retrieval_data(llm_retrieval_data)
    print(f"Split data into {len(chunks)} chunks to manage token limits")
    
    # 2. Process each chunk individually
    chunk_categorizations = []
    for i, chunk in enumerate(chunks):
        # 2a. Summarize each chunk if needed
        summarized_chunk = summarize_long_text(chunk, llm)
        
        # 2b. Categorize this chunk with a more generic instruction
        prompt = PromptTemplate.from_template(
            "Please analyze the following text and identify {context} that defines the text. "
            "For each identified statement; "
            "provide:\n"
            "1. The statement title\n"
            "2. Description of the statement\n"
            "3. Which collections this statement appears in\n"
            "4. Excerpt(s) from the collections and the citation with the page_number\n"

            "Example:"
            "1. Statement title\n"
            "2. Writing, whether traditional or digitalized, remains a complex and iterative process. The complexity of digitalized writing is further compounded by the use of multiple digital tools at different stages of the writing process.\n"
            "3. collection: A_Systematic_Review_of_ChatGPT\n"
            "4. Excerpt from the page_number: 39\n"
            "5. Mark Feng Teng Wright, et al."

            "Text to analyze:\n\n{text}"
        )
        
        chain = prompt | llm
        chunk_categorization = chain.invoke({"text": summarized_chunk, "context": "future study"})
        
        # Add chunk number to the categorization
        chunk_categorization.content = f"Chunk {i+1} overview:\n{chunk_categorization.content}"
        chunk_categorizations.append(chunk_categorization.content)
        
        # Optional: add delay between requests to avoid hitting rate limits
        # time.sleep(1)
    
    # 3. Combine results and write to file
    final_categorization = "\n\n---\n\n".join(chunk_categorizations)
    write_to_file('article_description.txt', final_categorization)
    
    # Output the categorized results
    print("Document Categorizations:")
    print(final_categorization)

if __name__ == '__main__':
    main()
