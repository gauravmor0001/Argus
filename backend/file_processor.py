import os
import shutil #used for high level file operations.
import fitz  # pymupdf — extracts images from PDF pages
import pytesseract   # runs OCR on images
from PIL import Image #used for opening,editing images
import io #helps in handling input/output more easily
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse, RetrievalMode
from langchain_core.documents import Document #this is used in langchain so that everypart know how to read , document contain 2 things content="" and metadata.


# Only needed if Tesseract isn't in your PATH automatically
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def extract_images_and_ocr(pdf_path: str, user_id: str) -> list[Document]:
    """
    Opens a PDF with pymupdf, finds every embedded image on every page,
    runs Tesseract OCR on each image, and returns a list of Documents.
    
    Each Document contains the OCR text and metadata identifying:
    - which page it came from
    - that it's image-extracted (not regular text)
    - which user uploaded it
    """
    ocr_docs = []

    try:
        pdf = fitz.open(pdf_path)
        print(f"DEBUG: Scanning {len(pdf)} pages for images...")

        for page_num in range(len(pdf)):
            page = pdf[page_num]

            # get_images() returns a list of image references on this page
            # each item is a tuple: (xref, smask, width, height, bpc, colorspace, ...)
            image_list = page.get_images(full=True)

            if not image_list:
                continue   # no images on this page, skip

            print(f"DEBUG: Page {page_num + 1} has {len(image_list)} image(s)")

            for img_index, img_ref in enumerate(image_list):
                xref = img_ref[0]    # xref is the image's unique ID inside the PDF

                try:
                    # extract_image() returns a dict with 'image' (raw bytes) and 'ext' (format)
                    base_image = pdf.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]   # e.g. "png", "jpeg"

                    # Convert raw bytes → PIL Image object so pytesseract can read it
                    image = Image.open(io.BytesIO(image_bytes))

                    # Convert to RGB — some PDFs embed CMYK or grayscale images
                    # Tesseract works best with RGB
                    if image.mode not in ("RGB", "L"):
                        image = image.convert("RGB")

                    # Run OCR — pytesseract.image_to_string() returns extracted text
                    ocr_text = pytesseract.image_to_string(image).strip()

                    # Skip images with no meaningful text (logos, decorative images, etc.)
                    # Less than 20 chars is usually just noise
                    if len(ocr_text) < 20:
                        print(f"DEBUG: Page {page_num+1}, image {img_index+1} — skipped (no useful text)")
                        continue

                    print(f"DEBUG: Page {page_num+1}, image {img_index+1} — OCR extracted {len(ocr_text)} chars")

                    # Wrap OCR text in a LangChain Document with rich metadata
                    doc = Document(
                        page_content=ocr_text,
                        metadata={
                            "source": pdf_path,
                            "page": page_num,
                            "image_index": img_index,
                            "source_type": "image_ocr", 
                            "user_id": user_id,
                            "image_format": image_ext
                        }
                    )
                    ocr_docs.append(doc)

                except Exception as img_err:
                    # One bad image shouldn't kill the whole upload
                    print(f"DEBUG: Skipping image {img_index} on page {page_num+1}: {img_err}")
                    continue

        pdf.close()
        print(f"DEBUG: OCR complete — extracted text from {len(ocr_docs)} image(s)")

    except Exception as e:
        # OCR failure is non-fatal — we still have the text content
        print(f"DEBUG: Image extraction failed (non-fatal): {e}")

    return ocr_docs

def ocr_scanned_pdf(pdf_path: str, user_id: str) -> list[Document]:
    """
    For scanned PDFs where PyPDFLoader returns empty text,
    render each PAGE as an image and OCR the whole page.
    
    This is the fallback for documents like scanned invoices,
    handwritten notes, or photographed pages.
    """
    ocr_docs = []

    try:
        pdf = fitz.open(pdf_path)

        for page_num in range(len(pdf)):
            page = pdf[page_num]

            # Render the page to a pixel map at 2x zoom (higher res = better OCR)
            # Matrix(2, 2) means 2x zoom in both dimensions → ~144 DPI
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)

            # Convert pixmap → PIL Image
            img_bytes = pix.tobytes("png")
            image = Image.open(io.BytesIO(img_bytes))

            ocr_text = pytesseract.image_to_string(image).strip()

            if len(ocr_text) < 20:
                continue

            print(f"DEBUG: Scanned page {page_num+1} — OCR extracted {len(ocr_text)} chars")

            doc = Document(
                page_content=ocr_text,
                metadata={
                    "source": pdf_path,
                    "page": page_num,
                    "source_type": "scanned_page_ocr", 
                    "user_id": user_id
                }
            )
            ocr_docs.append(doc)

        pdf.close()

    except Exception as e:
        print(f"DEBUG: Scanned PDF OCR failed (non-fatal): {e}")

    return ocr_docs


def process_and_ingest_document(file_obj,filename,embedding_model,sparse_embedding_model,user_id,chunk_size=1000):
    temp_filename=f"temp_{filename}"

    try:
        with open(temp_filename,"wb") as buffer: #write binary
            shutil.copyfileobj(file_obj,buffer)
        print(f"DEBUG: processing file:{temp_filename} for User ID:{user_id}")
        all_docs = []

        if temp_filename.endswith(".pdf"):
            loader = PyPDFLoader(temp_filename)
            text_docs = loader.load()

            # Check if this is a scanned PDF — PyPDFLoader returns empty strings for scanned docs
            total_text = " ".join([d.page_content for d in text_docs]).strip()
            is_scanned = len(total_text) < 100   # less than 100 chars total = probably scanned

            if is_scanned:
                # Entire pages are images — OCR the whole page render
                print(f"DEBUG: Detected scanned PDF — running full-page OCR")
                ocr_docs = ocr_scanned_pdf(temp_filename, user_id)
                all_docs.extend(ocr_docs)
            else:
                # Normal PDF — add text content AND extract embedded images
                print(f"DEBUG: Normal PDF — extracting text + embedded images")
                all_docs.extend(text_docs)

                # ── Step 3 (NEW): Extract images and OCR them ──
                image_ocr_docs = extract_images_and_ocr(temp_filename, user_id)
                all_docs.extend(image_ocr_docs)

                print(f"DEBUG: Text chunks: {len(text_docs)}, Image OCR chunks: {len(image_ocr_docs)}")

        elif temp_filename.endswith(".docx"):
            loader = Docx2txtLoader(temp_filename)
            all_docs.extend(loader.load())

        else:
            loader = TextLoader(temp_filename)
            all_docs.extend(loader.load())

        if not all_docs:
            return False, "No content could be extracted from this file."
        
    

        text_splitter=RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=200)
        splits=text_splitter.split_documents(all_docs)

        for split in splits:
            split.metadata["user_id"] = user_id
            split.metadata["filename"] = filename

        QdrantVectorStore.from_documents(
            splits,
            embedding_model,
            sparse_embedding=sparse_embedding_model, # Generates BM25 keywords for each chunk
            retrieval_mode=RetrievalMode.HYBRID,
            url="http://localhost:6333",
            # force_recreate=True, #delete the db and recreate it (true)
            collection_name="learning-rag"
        )
        has_ocr = any(s.metadata.get("source_type") in ("image_ocr", "scanned_page_ocr") for s in splits)
        msg = f"Successfully processed '{filename}'! Ingested {len(splits)} chunks"
        if has_ocr:
            msg += " (including text extracted from images via OCR)"

        return True, msg
        
    except Exception as e:
        return False, str(e)
        
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)