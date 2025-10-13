import streamlit as st
import PyPDF2
from io import BytesIO
import json

from langchain_groq.chat_models import ChatGroq
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_experimental.graph_transformers import LLMGraphTransformer
from pyvis.network import Network
import streamlit.components.v1 as components
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def extract_text_from_pdf(pdf_file: BytesIO) -> str:
    """
    Extracts text from a PDF file uploaded via Streamlit.
    
    Args:
        pdf_file (BytesIO): Uploaded PDF file object.
        
    Returns:
        str: Extracted text from the PDF.
    """
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except PyPDF2.errors.PdfReadError as e:
        st.error(f"Invalid PDF file: {e}")
        return ""
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
        return ""


def split_text_into_chunks(text: str, chunk_size: int = 1000, chunk_overlap: int = 200) -> list:
    """
    Splits text into chunks for processing.
    
    Args:
        text (str): Input text to split
        chunk_size (int): Maximum size of each chunk
        chunk_overlap (int): Overlap between consecutive chunks
        
    Returns:
        list: List of text chunks
    """
    try:
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len
        )
        return text_splitter.split_text(text)
    except Exception as e:
        st.error(f"Error splitting text into chunks: {e}")
        return [text]


def build_knowledge_graph(text: str, chunk_size: int, chunk_overlap: int) -> dict:
    """
    Uses an LLM to extract entities and relationships from text.
    
    Args:
        text (str): Input text to analyze
        chunk_size (int): Size of text chunk for processing
        chunk_overlap (int): Overlap between text chunk
        
    Returns:
        dict: Structured knowledge graph data
    """
    try:
        # Validate API keys
        groq_api_key = os.getenv("GROQ_API_KEY")
        
        if groq_api_key:
            llm = ChatGroq(
                temperature=0.1,
                model_name="llama-3.3-70b-versatile",
                groq_api_key=groq_api_key
            )
        else:
            st.warning("No valid LLM API key found. Please configure GROQ_API_KEY in your .env file.")
            return {"nodes": [], "edges": []}
            
        # Split text into chunks for large documents
        chunks = split_text_into_chunks(text, chunk_size, chunk_overlap)
        if not chunks:
            return {"nodes": [], "edges": []}
        
        # Initialize graph transformer
        graph_transformer = LLMGraphTransformer(llm=llm)
        
        # Process each chunk and aggregate results
        all_nodes = set()
        all_edges = []
        failed_chunks = []
        
        # Initialize progress bar and status message
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, chunk in enumerate(chunks):
            # Update progress and status
            progress = (i + 1) / len(chunks)
            progress_bar.progress(progress)
            status_text.text(f"Processing chunk {i + 1} of {len(chunks)}")
            
            try:
                # Convert chunk to document format expected by LLMGraphTransformer
                from langchain_core.documents import Document
                doc = Document(page_content=chunk)
                
                # Extract graph from chunk
                graph_documents = graph_transformer.convert_to_graph_documents([doc])
                
                # Extract nodes and edges from graph documents
                for graph_doc in graph_documents:
                    for node in graph_doc.nodes:
                        if hasattr(node, 'id') and hasattr(node, 'type'):
                            all_nodes.add((node.id, node.type))
                    for rel in graph_doc.relationships:
                        if hasattr(rel, 'source') and hasattr(rel, 'target') and hasattr(rel, 'type'):
                            all_edges.append({
                                "source": rel.source.id,
                                "target": rel.target.id,
                                "label": rel.type
                            })
                
            except Exception as e:
                st.error(f"Error processing chunk {i + 1}: {e}")
                failed_chunks.append(i + 1)
                continue
        
        # Clear progress and status
        progress_bar.empty()
        status_text.empty()
        
        # Report failed chunks
        if failed_chunks:
            st.warning(f"Failed to process chunk: {', '.join(map(str, failed_chunks))}")
        
        # Convert set to list
        nodes = [{"id": id, "label": label} for id, label in all_nodes]
        
        return {"nodes": nodes, "edges": all_edges}
        
    except Exception as e:
        st.error(f"Error building knowledge graph: {e}")
        return {"nodes": [], "edges": []}


def visualize_graph(graph_data: dict) -> str:
    """
    Creates an interactive HTML visualization of the knowledge graph.
    
    Args:
        graph_data (dict): Dictionary containing 'nodes' and 'edges' lists
        
    Returns:
        str: HTML content of the visualization
    """
    try:
        net = Network(notebook=False, height="500px", width="100%", directed=True)
        
        # Add nodes
        for node in graph_data.get("nodes", []):
            net.add_node(node["id"], label=node["label"])
            
        # Add edges
        for edge in graph_data.get("edges", []):
            # Check if both nodes exist before adding edge
            if net.get_node(edge["source"]) and net.get_node(edge["target"]):
                net.add_edge(edge["source"], edge["target"], label=edge.get("label", ""))
            else:
                st.warning(f"Skipping edge with non-existent node: {edge}")
                
        # Generate full HTML with all dependencies
        html_content = net.generate_html()
        
        return html_content
        
    except Exception as e:
        st.error(f"Error visualizing graph: {e}")
        return ""


def main():
    st.title("PDF Knowledge Graph Builder")
    st.subheader("Step 1: Upload PDF")

    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file is not None:
        st.info("PDF uploaded successfully!")
        text = extract_text_from_pdf(uploaded_file)
        
        if text:
            st.subheader("Extracted Text")
            st.text_area("Text content", value=text, height=300)
            
            # Add configuration sliders
            st.subheader("Processing Configuration")
            chunk_size = st.slider("Chunk Size", min_value=500, max_value=2000, value=1000, step=100)
            chunk_overlap = st.slider("Chunk Overlap", min_value=0, max_value=500, value=200, step=50)
            
            # Add chunk preview
            st.subheader("Chunk Preview")
            show_chunk_preview = st.checkbox("Show Chunk Preview")
            if show_chunk_preview:
                chunks = split_text_into_chunks(text, chunk_size, chunk_overlap)
                for i, chunk in enumerate(chunks):
                    with st.expander(f"Chunk {i + 1}"):
                        st.text_area(f"Chunk {i + 1} content", value=chunk, height=400)
                # Add chunk statistics
                st.subheader("Chunk Statistics")
                st.write(f"Total chunks: {len(chunks)}")
                st.write(f"Average chunk length: {sum(len(c) for c in chunks) // len(chunks)} characters")
                
                # Add chunk export
                chunk_data = [{"id": i + 1, "content": chunk} for i, chunk in enumerate(chunks)]
                st.download_button(
                    label="Export Chunks as JSON",
                    data=json.dumps(chunk_data, indent=2),
                    file_name="chunks.json",
                    mime="application/json"
                )
            
            if st.button("Process Text with LLM"):
                with st.spinner("Building knowledge graph..."):
                    graph_data = build_knowledge_graph(text=text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                    
                if graph_data["nodes"] or graph_data["edges"]:
                    st.subheader("Extracted Knowledge Graph")
                    st.json(graph_data)
                    
                    # Generate and display visualization
                    html_content = visualize_graph(graph_data)
                    if html_content:
                        components.html(html_content, height=800)
                        
                        # Add download button for visualization
                        st.download_button(
                            label="Download Graph Visualization",
                            data=html_content,
                            file_name="knowledge_graph.html",
                            mime="text/html"
                        )
                        
                        # Add JSON export
                        st.download_button(
                            label="Download Graph Data (JSON)",
                            data=json.dumps(graph_data, indent=2),
                            file_name="knowledge_graph.json",
                            mime="application/json"
                        )
                        
                        # Add CSV exports
                        nodes_csv = "id,label\n"
                        for node in graph_data.get("nodes", []):
                            nodes_csv += f"{node['id']},{node['label']}\n"
                            
                        edges_csv = "source,target,label\n"
                        for edge in graph_data.get("edges", []):
                            edges_csv += f"{edge['source']},{edge['target']},{edge.get('label', '')}\n"
                            
                        st.download_button(
                            label="Download Nodes List (CSV)",
                            data=nodes_csv,
                            file_name="nodes.csv",
                            mime="text/csv"
                        )
                        
                        st.download_button(
                            label="Download Edges List (CSV)",
                            data=edges_csv,
                            file_name="edges.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning("Failed to generate graph visualization.")
                else:
                    st.warning("No knowledge graph data extracted. Try a different PDF.")
                
        else:
            st.warning("No text extracted. Please upload a valid PDF.")


if __name__ == "__main__":
    main()
