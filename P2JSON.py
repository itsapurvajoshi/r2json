import streamlit as st
import google.generativeai as genai
import json
from PIL import Image
import io
import hashlib
import pypdfium2 as pdfium 
from st_clipboard import copy_to_clipboard # Import this at the top for cleaner usage

# Configure Gemini (replace with your API key)
# !!! CRITICAL SECURITY WARNING: Replace API Key with os.environ.get("GEMINI_API_KEY") for production/Git deployment !!!
genai.configure(api_key="AIzaSyAs9nSWf9tFCQNitvPcbuWDfMXaiTYXElQ")
model = genai.GenerativeModel('gemini-2.5-flash')

st.title("Receipt JSON Extractor")
st.write("Upload a photo or snap one with your camera for instant structured data.")

# Two-column layout
col1, col2 = st.columns(2)

# Upload section
with col1:
    st.subheader("📁 Upload File")
    st.markdown("**Drag and drop an image here**")
    upload_container = st.container()
    with upload_container:
        uploaded_file = st.file_uploader(
            "Choose a receipt image", 
            type=['jpg', 'jpeg', 'png', 'pdf'], 
            help="Limit 200MB per file. JPG, JPEG, PNG, or PDF",
            label_visibility="collapsed"
        )

# Camera section
with col2:
    st.subheader("📷 Take Photo")
    st.markdown("**Click a photo**")
    if 'camera_open' not in st.session_state:
        st.session_state.camera_open = False
    if 'camera_image' not in st.session_state:
        st.session_state.camera_image = None
    
    if not st.session_state.camera_open:
        if st.button("Open Camera", use_container_width=True):
            st.session_state.camera_open = True
            st.rerun()
    else:
        camera_container = st.container()
        with camera_container:
            new_camera_image = st.camera_input("Take a photo of the receipt")
            if new_camera_image:
                st.session_state.camera_image = new_camera_image
                st.rerun()

# --- FILE PROCESSING LOGIC (Unified) ---
image = None
uploaded_data = None

# Determine the source of the data
if st.session_state.camera_image is not None:
    uploaded_data = st.session_state.camera_image.getvalue()
    image = Image.open(io.BytesIO(uploaded_data))
elif uploaded_file is not None:
    uploaded_data = uploaded_file.getvalue()
    
    if uploaded_file.type == "application/pdf":
        # PDF MULTI-PAGE CONVERSION LOGIC
        try:
            pdf = pdfium.PdfDocument(uploaded_data)
            images = []
            
            # Loop through all pages and render
            for i in range(len(pdf)):
                page = pdf.get_page(i)
                img = page.render_topil(scale=300/72)
                images.append(img)
                page.close()

            pdf.close()

            # Combine vertically into one tall image
            widths, heights = zip(*(i.size for i in images))
            total_height = sum(heights)
            max_width = max(widths)
            
            combined_image = Image.new("RGB", (max_width, total_height), color=(255, 255, 255))
            y_offset = 0
            for img in images:
                combined_image.paste(img, (0, y_offset))
                y_offset += img.height
            
            image = combined_image
            st.success(f"Processed and combined all {len(images)} pages of the PDF.")
        except Exception as e:
            st.error(f"Could not process PDF: {e}")
            st.stop()
    else:
        # Handle regular image file (jpg/png)
        image = Image.open(io.BytesIO(uploaded_data))

# --- MAIN EXTRACTION & DISPLAY BLOCK ---
if image:
    # Compute hash for caching on the rendered image
    img_bytes = io.BytesIO()
    # Ensure image is RGB before saving as PNG for consistent hashing
    if image.mode not in ('RGB', 'RGBA', 'L'):
        image = image.convert('RGB')
    image.save(img_bytes, format='PNG') 
    image_hash = hashlib.md5(img_bytes.getvalue()).hexdigest()

    st.image(image, caption="Uploaded/Captured Receipt", width=400)

    # Check cache or extract
    if 'extracted_data' not in st.session_state:
        st.session_state.extracted_data = {}
    
    data = None

    if image_hash in st.session_state.extracted_data:
        # Data is cached
        data = st.session_state.extracted_data.get(image_hash)
    else:
        # Data needs to be extracted
        prompt = """
Analyze this detailed sales invoice/receipt (likely pharmaceutical or wholesale) and extract all line-item details into a structured JSON object.
[... Your long prompt is here ...]
"""
        with st.spinner("Extracting data..."):
            response = model.generate_content([prompt, image])
            extracted_json = response.text.strip()

        try:
            # Robust stripping
            if extracted_json.startswith('```json'):
                extracted_json = extracted_json.replace('```json', '').replace('```', '').strip()
            elif extracted_json.startswith('```'):
                extracted_json = extracted_json.replace('```', '').strip()
            extracted_json = extracted_json.lstrip('>json ').lstrip('json ').strip()

            # Parse and cache JSON
            data = json.loads(extracted_json)
            st.session_state.extracted_data[image_hash] = data
        except json.JSONDecodeError:
            st.error("Extraction failed—try a clearer image. Raw response: " + extracted_json)
            st.stop()

    # --- DISPLAY & DOWNLOAD SECTION (Unified) ---

    # 1. Get the invoice number for the PDF filename
    invoice_number = data.get("invoice_number", "Unidentified_Invoice")
    
    # 2. Format the filename
    safe_invoice_number = str(invoice_number).replace('/', '_').replace('\\', '_').strip()
    pdf_filename = f"{safe_invoice_number}.pdf"
    
    # 3. Create a BytesIO buffer to store the PDF data
    pdf_buffer = io.BytesIO()
    
    # 4. Save the current image to the buffer as a PDF
    try:
        # Save the PIL Image object as a single-page PDF
        image.save(pdf_buffer, format="PDF")
        pdf_buffer.seek(0) # Rewind the buffer

        st.subheader("Extracted JSON:")
        st.json(data)

        # Download PDF Button
        st.download_button(
            label="Download Receipt as PDF (Invoice No.) 💾",
            data=pdf_buffer,
            file_name=pdf_filename,
            mime="application/pdf"
        )
        
        # Download JSON Button
        st.download_button(
            "Download JSON", 
            json.dumps(data, indent=2), 
            "receipt.json"
        )

        # Copy JSON Button 
        copy_button = st.button("Copy JSON to clipboard")
        if copy_button:
            json_str = json.dumps(data, indent=2)
            # st_clipboard is already imported at the top
            copy_to_clipboard(json_str)
            st.success("JSON copied to clipboard!")
        
    except Exception as e:
        st.error(f"Error creating PDF or displaying data: {e}")

else:
    # This ensures the instruction message shows when no file is uploaded
    st.info("Please provide an image or PDF to start.")