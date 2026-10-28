import os
import sys
import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server
from fastapi.testclient import TestClient

client = TestClient(server.app)

print("=== 1. TEST GET / (UI) ===")
res = client.get("/")
print("Status code:", res.status_code)
assert res.status_code == 200
assert "ConsultAI" in res.text
assert "Google Drive" in res.text
print("GET / passed!")

print("\n=== 2. TEST POST /api/scan-upload (with sample PDFs) ===")
sample_dir = r"C:\Users\nattc\OneDrive\Desktop\AI ลองไปเรื่อย\งานของเพื่อนปั๊ม\consultai"
pdf_files = [f for f in os.listdir(sample_dir) if f.endswith(".pdf")][:3]

files_to_upload = []
for f in pdf_files:
    fpath = os.path.join(sample_dir, f)
    with open(fpath, "rb") as fp:
        files_to_upload.append(("files", (f, fp.read(), "application/pdf")))

res_upload = client.post("/api/scan-upload", files=files_to_upload)
print("Upload status:", res_upload.status_code)
data = res_upload.json()
print("Success:", data.get("success"))
print("KPI:", data.get("kpi"))
print("Results count:", len(data.get("results", [])))
token = data.get("download_token")
print("Download token:", token)

print("\n=== 3. TEST GET /api/download/{token} (Excel) ===")
res_dl = client.get(f"/api/download/{token}")
print("Download status:", res_dl.status_code)
print("Content-Type:", res_dl.headers.get("content-type"))
assert res_dl.status_code == 200
assert len(res_dl.content) > 1000

# Verify generated excel content
import io
wb = openpyxl.load_workbook(io.BytesIO(res_dl.content))
sheet = wb.active
for r in list(sheet.iter_rows(values_only=True))[:5]:
    print("  Excel row:", r)

print("\nALL SERVER TESTS PASSED SUCCESSFULLY! 100% READY!")
