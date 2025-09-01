from bs4 import BeautifulSoup
import requests

# Example HTML content
html_content = '''
<div class="gs_or_ggsm" ontouchstart="gs_evt_dsp(event)" tabindex="-1">
    <a href="https://repository.isls.org/bitstream/1/11196/1/ICLS2024_963-966.pdf" 
       data-clk="hl=en&amp;sa=T&amp;oi=gga&amp;ct=gga&amp;cd=0&amp;d=2875642583945101498&amp;ei=Vtq0aOrIFODM6rQPycS0-AI" 
       data-clk-atid="usAIvbFV6CcJ">
        <span class="gs_ctg2">[PDF]</span> isls.org
    </a>
</div>
'''

# Parse the HTML content
soup = BeautifulSoup(html_content, 'html.parser')

# Find the PDF link using multiple strategies
# 1. Try the CSS selector
pdf_link = soup.select_one('div.gs_or_ggsm a')
print(f"Strategy 1 result: {pdf_link}")

# 2. If that fails, try finding by text
if not pdf_link:
    pdf_link = soup.find('a', text=lambda t: t and '[PDF]' in t)
    print(f"Strategy 2 result: {pdf_link}")

# 3. If that fails, just find any link in the div
if not pdf_link:
    pdf_div = soup.find('div', class_='gs_or_ggsm')
    if pdf_div:
        pdf_link = pdf_div.find('a', href=True)
        print(f"Strategy 3 result: {pdf_link}")

# Check if the link exists and is a PDF
if pdf_link and pdf_link.get('href', '').endswith('.pdf'):
    pdf_url = pdf_link['href']
    # Download the PDF
    response = requests.get(pdf_url)
    if response.status_code == 200:
        # Save the PDF to a file
        with open('downloaded_file.pdf', 'wb') as f:
            f.write(response.content)
        print("PDF saved as 'downloaded_file.pdf'")
    else:
        print("Failed to download PDF. Status code:", response.status_code)
else:
    print("No PDF link found.")
