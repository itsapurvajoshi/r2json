import streamlit as st
import google.generativeai as genai
import json
from PIL import Image
import io
import hashlib
import pypdfium2 as pdfium
# Configure Gemini (replace with your API key)

genai.configure(api_key="AIzaSyAs9nSWf9tFCQNitvPcbuWDfMXaiTYXElQ")
model = genai.GenerativeModel('gemini-2.5-flash')  # Fast & cheap; use 'gemini-2.5-pro' for higher accuracy
st.title("Receipt JSON Extractor")
st.write("Upload a photo or snap one with your camera for instant structured data.")
# Two-column layout
col1, col2 = st.columns(2)
# Upload section - flattened and enlarged visual area

with col1:
    st.subheader("📁 Upload File")
    st.markdown("**Drag and drop an image here**")
    # Use a container for visual spacing to make the area feel bigger
    upload_container = st.container()
    with upload_container:
        uploaded_file = st.file_uploader(
            "Choose a receipt image",
            type=['jpg', 'jpeg', 'png', 'pdf'],
            help="Limit 200MB per file. JPG, JPEG, PNG, or PDF",
            label_visibility="collapsed"  # Hides the default label to focus on drag-drop
        )

# Camera section - symmetric, no expander, with button to trigger camera

with col2:
    st.subheader("📷 Take Photo")
    st.markdown("**Click a photo**")
    # Initialize session state for camera toggle and image
    if 'camera_open' not in st.session_state:
        st.session_state.camera_open = False
    if 'camera_image' not in st.session_state:
        st.session_state.camera_image = None

    if not st.session_state.camera_open:
        if st.button("Open Camera", use_container_width=True):
            st.session_state.camera_open = True
            st.rerun()  # Rerun to render the camera immediately

    else:
        # Camera input only renders when open; store in session state
        camera_container = st.container()
        with camera_container:
            new_camera_image = st.camera_input("Take a photo of the receipt")
            if new_camera_image:
                st.session_state.camera_image = new_camera_image
                st.rerun()

# Process image if available (prioritize camera if both)

image = None
image_hash = None
uploaded_data = None

if st.session_state.camera_image is not None:
    # Handle Camera Input
    uploaded_data = st.session_state.camera_image.getvalue()
    image = Image.open(io.BytesIO(uploaded_data))
    
elif uploaded_file is not None:
    # Handle Uploaded File
    uploaded_data = uploaded_file.getvalue()
    
    if uploaded_file.type == "application/pdf":
        # --- PDF CONVERSION LOGIC ---
        try:
            # Load PDF from bytes
            pdf = pdfium.PdfDocument(uploaded_data)
            # Render the first page (index 0) to a PIL Image object at 300 DPI
            page = pdf.get_page(0)
            image = page.render_topil(scale=300/72) 
            page.close()
            pdf.close()
            st.warning("Processed first page of the PDF.")
        except Exception as e:
            st.error(f"Could not process PDF: {e}")
            st.stop()
        # --- END PDF CONVERSION LOGIC ---
        
    else:
        # Handle regular image file (jpg/png)
        image = Image.open(io.BytesIO(uploaded_data))

# Now, compute the hash for the final image if it exists
if image:
    # Compute hash for caching on the rendered image
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG') # Save as PNG for consistent hashing
    image_hash = hashlib.md5(img_bytes.getvalue()).hexdigest()

# --- CONTINUE WITH THE REST OF YOUR ORIGINAL CODE (st.image, st.spinner, etc.) ---
if image:
    st.image(image, caption="Uploaded/Captured Receipt", width=400)
    # Check cache or extract

    if 'extracted_data' not in st.session_state:
        st.session_state.extracted_data = {}

    if image_hash and image_hash not in st.session_state.extracted_data:
        # Prompt for structured JSON extraction
        prompt = """
Analyze this detailed sales invoice/receipt (likely pharmaceutical or wholesale) and extract all line-item details into a structured JSON object.

Output structure must include:
- merchant: string (store name)
- date: string (YYYY-MM-DD)
- invoice_number: string (the bill number)
- total_net_amount: number (Final amount paid)
- total_discount: number (Total discount for the whole bill in persentage, 0 if none)
- total_gst: number (Total GST/Tax for the whole bill in percentage, 0 if none)
- items: array of objects. Each object must contain the following fields, in this exact order:
    - name: string (Item name/Description)
    - hsn: string (HSN/SAC code, if present)
    - mfg: string (Manufacturer/Brand)
    - pack: string (Pack size, e.g., 10 TAB)
    - batch: string (Batch number)
    - expiry: string (Expiry date, format YYYY-MM-DD or MM/YYYY)
    - quantity: number (Quantity purchased)
    - free: number (Free quantity received, 0 if none)
    - mrp_old: number (Old MRP, 0 if not present)
    - mrp_new: number (New or current MRP)
    - mrp: number (The actual selling unit MRP)
    - rate: number (The actual selling unit rate)
    - discount_percentage: number (Item-level discount percentage, 0 if none)
    - gst_percentage: number (Item-level GST percentage)
    - amount: number (Final line total amount)

If a field is not present on the receipt (e.g., HSN, free quantity), set its value to 0 for numbers and an empty string ("") for strings.
Output ONLY valid JSON, no extra text, no markdown fences (```json).

"""
        with st.spinner("Extracting data..."):
            response = model.generate_content([prompt, image])
            extracted_json = response.text.strip()

        try:
            # Robust stripping: markdown fences, prefixes like '>json' or 'json ', and extra whitespace
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
            st.stop()  # Halt if extraction fails

    # Retrieve from cache (or just extracted)

    data = st.session_state.extracted_data.get(image_hash)
    
    # ----------------------------------------------------
    # NEW FEATURE LOGIC: Prepare PDF download
    # ----------------------------------------------------
    
    # 1. Get the invoice number, safely handling case where it might be missing
    invoice_number = data.get("invoice_number", "Unidentified_Invoice")
    
    # 2. Format the filename
    pdf_filename = f"{invoice_number}.pdf"
    
    # 3. Create a BytesIO buffer to store the PDF data
    pdf_buffer = io.BytesIO()
    
    # 4. Save the current image to the buffer as a PDF
    # The 'image' variable holds the PIL Image object (either from JPG/PNG or converted from PDF)
    try:
        image.save(pdf_buffer, format="PDF")
        pdf_buffer.seek(0) # Rewind the buffer to the start
        
        # ----------------------------------------------------
        # Streamlit Output and Download Buttons
        # ----------------------------------------------------
        st.subheader("Extracted JSON:")
        st.json(data)

        # Download PDF Button
        st.download_button(
            label="Download Receipt as PDF (Invoice No.)",
            data=pdf_buffer,
            file_name=pdf_filename,
            mime="application/pdf"
        )
        
        # Download JSON Button (Move your existing download button here)
        st.download_button(
            "Download JSON", 
            json.dumps(data, indent=2), 
            "receipt.json"
        )

        # Copy JSON Button (Keep your clipboard logic here)
        copy_button = st.button("Copy JSON to clipboard")
        if copy_button:
            json_str = json.dumps(data, indent=2)
            # You need the st_clipboard import here if you didn't put it at the top
            from st_clipboard import copy_to_clipboard 
            copy_to_clipboard(json_str)
            st.success("JSON copied to clipboard!")
        
    except Exception as e:
        st.error(f"Error creating PDF: {e}")

else:
    st.info("Please provide an image or PDF to start.")