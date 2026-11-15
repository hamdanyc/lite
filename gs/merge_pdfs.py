import os
from pypdf import PdfWriter, PdfReader

def get_word_count(pdf_path):
    """
    Estimates the word count of a PDF file by extracting text from all pages.
    """
    word_count = 0
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                word_count += len(text.split())
    except Exception as e:
        print(f"  Warning: Could not count words in {os.path.basename(pdf_path)}: {e}")
    return word_count

def merge_pdfs(input_dir, output_dir, max_files=50, max_words=500000):
    """
    Merges PDF files from input_dir into single PDFs.
    Each batch is limited to max_files OR max_words.
    Saves the result to output_dir with the name 'src_batch_#.pdf'.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")

    # Get all PDF files and sort them
    pdf_files = sorted([f for f in os.listdir(input_dir) if f.lower().endswith('.pdf')])
    total_files = len(pdf_files)
    print(f"Found {total_files} PDF files in {input_dir}")

    current_batch_files = []
    current_word_count = 0
    batch_num = 1

    def save_batch(files, b_num, w_count):
        output_filename = f"src_batch_{b_num}.pdf"
        output_path = os.path.join(output_dir, output_filename)
        merger = PdfWriter()
        print(f"Saving batch {b_num}: {len(files)} files, approx {w_count} words -> {output_filename}")
        
        for pdf in files:
            pdf_path = os.path.join(input_dir, pdf)
            try:
                merger.append(pdf_path)
            except Exception as e:
                print(f"  Error appending {pdf}: {e}")
        
        with open(output_path, "wb") as f_out:
            merger.write(f_out)
        merger.close()
        print(f"Successfully saved {output_filename}")

    for pdf in pdf_files:
        pdf_path = os.path.join(input_dir, pdf)
        pdf_words = get_word_count(pdf_path)
        
        # Check if adding this file exceeds limits
        if (len(current_batch_files) >= max_files) or (current_word_count + pdf_words > max_words):
            if current_batch_files:
                save_batch(current_batch_files, batch_num, current_word_count)
                batch_num += 1
                current_batch_files = []
                current_word_count = 0
        
        current_batch_files.append(pdf)
        current_word_count += pdf_words

    # Save the last batch
    if current_batch_files:
        save_batch(current_batch_files, batch_num, current_word_count)

if __name__ == "__main__":
    input_directory = "pdf"
    output_directory = "merged_pdfs"
    merge_pdfs(input_directory, output_directory, max_files=50, max_words=500000)
