import os
import subprocess

def verify_and_rename_pdf_files(directory):
    # Get all files in the directory
    files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    
    print(f"Found {len(files)} files in {directory}")
    
    for filename in files:
        file_path = os.path.join(directory, filename)
        
        # Skip directories
        if not os.path.isfile(file_path):
            continue
            
        # Check if file has .pdf extension
        if not filename.lower().endswith('.pdf'):
            print(f"Skipping non-PDF file: {filename}")
            continue
            
        # Check if file is actually a PDF using file command
        result = subprocess.run(['file', '--mime-type', '-b', file_path], capture_output=True, text=True)
        file_mime = result.stdout.strip()
        
        if file_mime == 'application/pdf':
            print(f"✅ Valid PDF: {filename}")
        else:
            # Rename file by removing .pdf extension
            new_filename = filename[:-4]  # Remove last 4 characters (.pdf)
            new_file_path = os.path.join(directory, new_filename)
            
            os.rename(file_path, new_file_path)
            print(f"❌ Not a PDF: {filename} → Renamed to {new_filename}")

if __name__ == '__main__':
    pdf_directory = 'pdf'
    verify_and_rename_pdf_files(pdf_directory)
