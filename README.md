# ConsultAI — CLD Logic Diagram Inspector 🛠️

ระบบตรวจสอบแบบแปลน Control Logic Diagram (CLD) อัจฉริยะสำหรับงานวิศวกรรม (ConsultAI)
ช่วยคัดกรอง แยกแยะประเภท IO CLD vs NOT IO CLD สกัด Position Code (CLD_No1, CLD_No2, CLD_No3) และดึงรหัส Model Card (IMCIS22) อัตโนมัติ พร้อมส่งมอบเป็นไฟล์ Excel (.xlsx)

---

## 🚀 ฟีเจอร์หลัก
1. **แยกแยะประเภท Drawing:**
   - ตรวจจับสัญลักษณ์ Input/Output Logic Diagram (`IO CLD` vs `NOT IO CLD`)
2. **ดึง Position Code อัตโนมัติ:**
   - ดึงรหัสตำแหน่งเฉพาะของเอกสาร (เช่น `2-2-7`, `2-2-8`) แยกเป็น 3 คอลัมน์ย่อย (`CLD_No1`, `CLD_No2`, `CLD_No3`)
3. **อ่านรหัส Model Card:**
   - สแกนหาบล็อกการ์ดกลางหน้าเอกสาร (เช่น `IMCIS22`)
4. **ส่งออก Excel มาตรฐาน:**
   - ฟอร์แมตหัวตารางสีน้ำเงิน Navy Blue สลับแถวไฮไลต์สีเขียว/เทา สวยงามพร้อมส่งต่อทันที
5. **รองรับ 2 ช่องทางประมวลผล:**
   - **Google Drive Link:** เพียงวางลิงก์โฟลเดอร์ Google Drive แบบสาธารณะ ("ทุกคนที่มีลิงก์")
   - **Direct Drag & Drop:** ลากไฟล์ PDF หรือโฟลเดอร์ ZIP มาหย่อนใส่หน้าเว็บได้โดยตรง

---

## 💻 วิธีการรันในเครื่อง (Local Run)

```bash
# ติดตั้งไลบรารี
pip install -r requirements.txt

# สตาร์ทเซิร์ฟเวอร์
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```
เปิดเบราว์เซอร์ไปที่: `http://localhost:8000`

---

## 🌐 Deploy to Cloud (Render / Railway / Docker)

- **Docker:**
  ```bash
  docker build -t consultai-cld-inspector .
  docker run -p 8000:8000 consultai-cld-inspector
  ```
- **Render.com:**
  สร้าง Web Service ใหม่บน Render แล้วเชื่อมกับ GitHub Repository นี้ ระบบจะตรวจจับ `render.yaml` และ deploy อัตโนมัติ
