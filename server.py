#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ConsultAI CLD Inspector: Web Application Server (FastAPI)
Provides API endpoints for uploading and analyzing Control Logic Diagrams (PDFs),
Google Drive folder synchronization, and Excel report generation.
"""

import os
import io
import time
import uuid
import zipfile
import tempfile
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime

import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Local imports
from engine import process_multiple_pdfs, generate_excel_report
from gdrive import download_and_extract_pdfs

# App initialization
app = FastAPI(
    title="ConsultAI CLD Inspector",
    description="Intelligent Control Logic Diagram (CLD) Inspector & Classifier",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directory configurations
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STORAGE_DIR = os.path.join(tempfile.gettempdir(), "consultai_cld_cache")
os.makedirs(STORAGE_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# In-memory storage mapping token -> report metadata
REPORTS_STORE: Dict[str, Dict[str, Any]] = {}

class GDriveRequest(BaseModel):
    gdrive_url: Optional[str] = None

def compute_kpi(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculates KPI statistics from classification results."""
    total = len(results)
    io_cld = sum(1 for r in results if r.get("Status") == "IO CLD")
    not_io_cld = sum(1 for r in results if r.get("Status") == "NOT IO CLD")
    errors = sum(1 for r in results if r.get("Status") == "ERROR")
    ratio = round((io_cld / total * 100), 1) if total > 0 else 0.0
    
    return {
        "total": total,
        "io_cld": io_cld,
        "not_io_cld": not_io_cld,
        "errors": errors,
        "io_percentage": f"{ratio}%",
        "ratio_raw": ratio
    }

def store_result_and_excel(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generates Excel workbook, stores metadata, and generates access token."""
    token = uuid.uuid4().hex[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_filename = f"Result_CLD_Inspection_{timestamp}.xlsx"
    excel_path = os.path.join(STORAGE_DIR, f"{token}_{excel_filename}")
    
    # Save Excel report to disk
    generate_excel_report(results, output_path=excel_path)
    
    kpi = compute_kpi(results)
    
    REPORTS_STORE[token] = {
        "excel_path": excel_path,
        "filename": excel_filename,
        "created_at": time.time(),
        "kpi": kpi,
        "results": results
    }
    
    return {
        "status": "success",
        "download_token": token,
        "download_url": f"/api/download/{token}",
        "filename": excel_filename,
        "kpi": kpi,
        "results": results
    }

# ----------------- ROUTE HANDLERS -----------------

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Renders the main modern dashboard UI."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.post("/api/scan-upload")
async def scan_upload(files: List[UploadFile] = File(...)):
    """
    Accepts multiple PDF files or a ZIP archive containing CLD drawings.
    Inspects drawings and returns classification results with Excel download token.
    """
    if not files:
        raise HTTPException(status_code=400, detail="กรุณาเลือกไฟล์ PDF หรือ ZIP เพื่อทำการสแกน")
        
    file_items = []
    
    for file in files:
        fname = file.filename or "unknown_file"
        fname_lower = fname.lower()
        content = await file.read()
        
        if fname_lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as z:
                    for info in z.infolist():
                        if info.filename.lower().endswith(".pdf") and not os.path.basename(info.filename).startswith("."):
                            pdf_bytes = z.read(info)
                            file_items.append((os.path.basename(info.filename), pdf_bytes))
            except Exception as ze:
                raise HTTPException(status_code=400, detail=f"ไม่สามารถเปิดไฟล์ ZIP {fname} ได้: {str(ze)}")
        elif fname_lower.endswith(".pdf"):
            file_items.append((fname, content))
            
    if not file_items:
        raise HTTPException(
            status_code=400, 
            detail="ไม่พบไฟล์ Drawing PDF ในรายการที่เลือก กรุณาอัปโหลดไฟล์ที่มีนามสกุล .pdf หรือ .zip ที่มีไฟล์ pdf อยู่ภายใน"
        )
        
    # Sort files by filename
    file_items.sort(key=lambda x: x[0])
    
    try:
        results = process_multiple_pdfs(file_items)
        response_data = store_result_and_excel(results)
        return JSONResponse(content=response_data)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาดในการประมวลผล Drawing: {str(e)}")

@app.post("/api/scan-gdrive")
async def scan_gdrive(request: Request):
    """
    Accepts Google Drive URL (folder or zip/pdf file).
    Downloads files via gdrive module and processes them through the engine.
    """
    # Parse URL from JSON body or Form data
    gdrive_url = None
    content_type = request.headers.get("content-type", "")
    
    if "application/json" in content_type:
        try:
            body = await request.json()
            gdrive_url = body.get("gdrive_url")
        except Exception:
            pass
    else:
        form = await request.form()
        gdrive_url = form.get("gdrive_url")
        
    if not gdrive_url or not str(gdrive_url).strip():
        raise HTTPException(status_code=400, detail="กรุณาระบุลิงก์ Google Drive Folder หรือ File")
        
    gdrive_url = str(gdrive_url).strip()
    
    # Download folder/files to unique temp directory
    temp_dir = tempfile.mkdtemp(prefix="gdrive_scan_")
    
    try:
        pdf_items = download_and_extract_pdfs(gdrive_url, dest_dir=temp_dir)
        results = process_multiple_pdfs(pdf_items)
        response_data = store_result_and_excel(results)
        return JSONResponse(content=response_data)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except FileNotFoundError as fe:
        raise HTTPException(status_code=404, detail=str(fe))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาดในการดึงข้อมูลจาก Google Drive: {str(e)}")

@app.get("/api/download/{token}")
async def download_excel(token: str):
    """Downloads the generated Excel report matching the provided token."""
    report_info = REPORTS_STORE.get(token)
    if not report_info:
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์ผลลัพธ์หรือลิงก์หมดอายุ กรุณาทำการสแกนใหม่อีกครั้ง")
        
    excel_path = report_info.get("excel_path")
    filename = report_info.get("filename", "Result_CLD_Inspection.xlsx")
    
    if not excel_path or not os.path.exists(excel_path):
        raise HTTPException(status_code=404, detail="ไฟล์ผลลัพธ์บนเซิร์ฟเวอร์ถูกลบแล้ว กรุณาทำการสแกนใหม่อีกครั้ง")
        
    return FileResponse(
        path=excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename
    )

@app.get("/api/demo-sample")
async def run_demo_sample():
    """Quick demo endpoint running on local sample PDFs for instant UI verification."""
    sample_dir = os.path.join(os.path.dirname(BASE_DIR), "consultai")
    if not os.path.exists(sample_dir):
        raise HTTPException(status_code=404, detail="ไม่พบโฟลเดอร์ตัวอย่าง consultai")
        
    sample_files = sorted([f for f in os.listdir(sample_dir) if f.lower().endswith(".pdf")])
    if not sample_files:
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์ตัวอย่าง PDF")
        
    file_items = [(f, os.path.join(sample_dir, f)) for f in sample_files]
    results = process_multiple_pdfs(file_items)
    response_data = store_result_and_excel(results)
    return JSONResponse(content=response_data)

@app.get("/api/health")
async def health_check():
    """System health check endpoint."""
    return {
        "status": "healthy",
        "service": "ConsultAI CLD Inspector",
        "active_cached_reports": len(REPORTS_STORE),
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    print("Starting ConsultAI CLD Inspector Server on http://localhost:8000 ...")
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
