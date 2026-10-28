#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ConsultAI: Google Drive Folder PDF Downloader Module
โมดูลดาวน์โหลดไฟล์แบบแปลน (.pdf) ทั้งหมดจากโฟลเดอร์ Google Drive
พร้อมระบบตรวจสอบสิทธิ์การเข้าถึง และจัดการ Error ภาษาไทยอย่างชัดเจน
"""

import os
import re
import sys
import zipfile
import tempfile
import logging
from typing import List, Tuple, Optional
import gdown
from gdown.exceptions import DownloadError

# ป้องกันปัญหา UnicodeEncodeError บน Windows terminal (cp874/cp1252)
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ตั้งค่า Logger ประจำโมดูล
logger = logging.getLogger("gdrive_downloader")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class GDriveError(Exception):
    """ข้อยกเว้นพื้นฐานสำหรับข้อผิดพลาดในการดาวน์โหลด Google Drive"""
    pass


class GDrivePermissionError(GDriveError, PermissionError):
    """ข้อยกเว้นเมื่อโฟลเดอร์หรือไฟล์ไม่ได้เปิดสิทธิ์แชร์ หรือไม่สามารถเข้าถึงได้"""
    pass


class GDriveInvalidURLError(GDriveError, ValueError):
    """ข้อยกเว้นเมื่อ URL หรือ Folder ID ไม่ถูกต้องตามรูปแบบที่กำหนด"""
    pass


def extract_gdrive_folder_id(folder_url_or_id: str) -> Tuple[str, str]:
    """
    สกัดและตรวจสอบ Folder ID หรือ File ID จาก URL หรือ ID ของ Google Drive

    Returns
    -------
    Tuple[str, str]
        (resource_type, resource_id) โดย resource_type คือ 'folder' หรือ 'file'
    """
    if not folder_url_or_id or not isinstance(folder_url_or_id, str):
        raise GDriveInvalidURLError("กรุณาระบุ URL หรือ Folder ID ของ Google Drive")

    cleaned = folder_url_or_id.strip()

    # 1. ลิงก์โฟลเดอร์มาตรฐาน: /folders/<id>
    folder_match = re.search(r'/folders/([a-zA-Z0-9_-]+)', cleaned)
    if folder_match:
        return 'folder', folder_match.group(1)

    # 2. พารามิเตอร์ query id: ?id=<id> หรือ &id=<id>
    id_param_match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', cleaned)
    if id_param_match:
        if 'file' in cleaned.lower():
            return 'file', id_param_match.group(1)
        return 'folder', id_param_match.group(1)

    # 3. ลิงก์ไฟล์เดี่ยว: /file/d/<id>
    file_match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', cleaned)
    if file_match:
        return 'file', file_match.group(1)

    # 4. หากผู้ใช้ระบุเป็น Folder ID มาโดยตรง (ตัวอักษร ตัวเลข ขีดล่าง ขีดกลาง ความยาว 10 ตัวอักษรขึ้นไป)
    if re.match(r'^[a-zA-Z0-9_-]{10,}$', cleaned):
        return 'folder', cleaned

    raise GDriveInvalidURLError(
        "รูปแบบ URL หรือ Folder ID ไม่ถูกต้อง กรุณาใช้ลิงก์โฟลเดอร์ Google Drive ในรูปแบบ "
        "https://drive.google.com/drive/folders/xxxx หรือระบุ Folder ID ให้ถูกต้อง"
    )


def extract_gdrive_id(url_or_id: str) -> Tuple[str, str]:
    """Alias สำหรับ backward compatibility กับโค้ดเดิม"""
    return extract_gdrive_folder_id(url_or_id)


def download_from_gdrive_folder(
    folder_url_or_id: str,
    dest_dir: str,
    quiet: bool = True,
    max_files: Optional[int] = None
) -> List[str]:
    """
    ดาวน์โหลดไฟล์ .pdf ทั้งหมดจากโฟลเดอร์ Google Drive ลงใน dest_dir

    Parameters
    ----------
    folder_url_or_id : str
        URL ของโฟลเดอร์ Google Drive (เช่น https://drive.google.com/drive/folders/xxxx)
        หรือ Folder ID
    dest_dir : str
        โฟลเดอร์ปลายทางในเครื่องสำหรับจัดเก็บไฟล์ .pdf
    quiet : bool, optional
        ซ่อนความคืบหน้าของ gdown (ค่าเริ่มต้นคือ True)
    max_files : int, optional
        จำกัดจำนวนไฟล์ .pdf สูงสุดที่จะดาวน์โหลด (ค่าเริ่มต้นคือ None = ดาวน์โหลดทั้งหมด)

    Returns
    -------
    List[str]
        รายการ Absolute Path ของไฟล์ .pdf ทั้งหมดที่ดาวน์โหลดสำเร็จ

    Raises
    ------
    GDriveInvalidURLError
        เมื่อรูปแบบ URL หรือ Folder ID ไม่ถูกต้อง
    GDrivePermissionError
        เมื่อโฟลเดอร์ไม่ได้เปิดแชร์เป็น Anyone with the link can view หรือไม่พบโฟลเดอร์
    ConnectionError
        เมื่อเกิดปัญหาการเชื่อมต่อเครือข่าย
    RuntimeError
        เมื่อเกิดข้อผิดพลาดจาก Google Drive เช่น โควต้าดาวน์โหลดเกิน
    """
    # 1. สกัดและตรวจสอบประเภททรัพยากรและ ID
    res_type, res_id = extract_gdrive_folder_id(folder_url_or_id)

    # 2. เตรียมโฟลเดอร์ปลายทาง
    os.makedirs(dest_dir, exist_ok=True)
    abs_dest_dir = os.path.abspath(dest_dir)

    # 3. จัดการกรณีผู้ใช้ระบุลิงก์เป็นไฟล์เดี่ยว (PDF หรือ ZIP)
    if res_type == 'file':
        logger.info(f"ตรวจพบเป็นลิงก์ไฟล์เดี่ยว Google Drive (File ID: {res_id})")
        target_file = os.path.join(abs_dest_dir, f"{res_id}_download")
        try:
            downloaded = gdown.download(id=res_id, output=target_file, quiet=quiet, resume=True)
            if not downloaded or not os.path.exists(downloaded):
                return []

            # แตก ZIP ถ้าเป็นไฟล์บีบอัด
            if downloaded.lower().endswith(".zip") or zipfile.is_zipfile(downloaded):
                try:
                    with zipfile.ZipFile(downloaded, 'r') as z:
                        z.extractall(abs_dest_dir)
                except Exception as ze:
                    logger.warning(f"ไม่สามารถแตกไฟล์ ZIP ได้: {ze}")
        except DownloadError as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ["permission", "anyone with the link", "404", "403", "cannot retrieve", "failed to retrieve"]):
                raise GDrivePermissionError(
                    "ไม่สามารถเข้าถึงไฟล์ Google Drive ได้ กรุณาตั้งค่าไฟล์ Google Drive ให้เป็น "
                    "'Anyone with the link can view' (ทุกคนที่มีลิงก์มีสิทธิ์ดู) และตรวจสอบว่า File ID ถูกต้อง"
                ) from e
            raise RuntimeError(f"เกิดข้อผิดพลาดในการดาวน์โหลดไฟล์เดี่ยว: {e}") from e

        # รวบรวม PDF ทั้งหมดใน dest_dir
        pdf_paths = []
        for root, _, files in os.walk(abs_dest_dir):
            for f in files:
                if f.lower().endswith(".pdf") and not f.startswith("."):
                    pdf_paths.append(os.path.abspath(os.path.join(root, f)))
        pdf_paths.sort()
        return pdf_paths

    # 4. ดาวน์โหลดจากโฟลเดอร์ Google Drive
    logger.info(f"กำลังสแกนและดึงรายการไฟล์จากโฟลเดอร์ Google Drive (Folder ID: {res_id})...")
    folder_items = None
    try:
        # ใช้ skip_download=True เพื่อดึงรายชื่อไฟล์ก่อน ดาวน์โหลดเฉพาะไฟล์เป้าหมาย (.pdf, .zip)
        # ช่วยประหยัดแบนด์วิดท์และความเร็วได้มหาศาล โดยไม่ต้องโหลดไฟล์วิดีโอหรือไฟล์อื่นๆ
        folder_items = gdown.download_folder(
            id=res_id,
            output=abs_dest_dir,
            skip_download=True,
            quiet=quiet
        )
    except DownloadError as e:
        err_str = str(e).lower()
        if any(k in err_str for k in ["permission", "anyone with the link", "404", "403", "cannot retrieve", "failed to retrieve"]):
            raise GDrivePermissionError(
                "ไม่สามารถเข้าถึงโฟลเดอร์ Google Drive ได้ กรุณาตั้งค่าโฟลเดอร์ Google Drive ให้เป็น "
                "'Anyone with the link can view' (ทุกคนที่มีลิงก์มีสิทธิ์ดู) และตรวจสอบว่า Folder ID ถูกต้อง"
            ) from e
        elif "quota" in err_str or "too many" in err_str:
            raise RuntimeError(
                "Google Drive จำกัดการดาวน์โหลดชั่วคราวเนื่องจากมีการดาวน์โหลดเกินโควต้า กรุณาลองใหม่อีกครั้งในภายหลัง"
            ) from e
        else:
            raise RuntimeError(f"เกิดข้อผิดพลาดในการเข้าถึงโฟลเดอร์ Google Drive: {e}") from e
    except Exception as e:
        err_msg = str(e).lower()
        if "connection" in err_msg or "timeout" in err_msg:
            raise ConnectionError("เกิดข้อผิดพลาดในการเชื่อมต่ออินเทอร์เน็ต กรุณาตรวจสอบสัญญาณเน็ตแล้วลองใหม่อีกครั้ง") from e
        # กรณี skip_download ล้มเหลวด้วยสาเหตุอื่น พยายามดาวน์โหลดแบบปกติเป็น fallback
        logger.warning(f"skip_download ไม่สำเร็จ ({e}) กำลังใช้โหมด fallback...")

    # 5. ประมวลผลและดาวน์โหลดไฟล์เป้าหมาย
    if folder_items is not None:
        # กรองเฉพาะไฟล์นามสกุล .pdf หรือ .zip
        target_items = [
            item for item in folder_items
            if hasattr(item, "path") and item.path and (
                item.path.lower().endswith(".pdf") or item.path.lower().endswith(".zip")
            )
        ]
        logger.info(f"พบไฟล์เอกสารเป้าหมาย (.pdf/.zip) ทั้งหมด {len(target_items)} ไฟล์ (จากทั้งหมด {len(folder_items)} ไฟล์)")

        if not target_items:
            logger.warning("ไม่พบไฟล์นามสกุล .pdf หรือ .zip ในโฟลเดอร์ Google Drive ที่ระบุ")
            return []

        # ตัดจำนวนถ้ามี max_files
        if max_files and max_files > 0:
            target_items = target_items[:max_files]

        for idx, item in enumerate(target_items, 1):
            rel_path = os.path.normpath(item.path)
            target_file_path = os.path.join(abs_dest_dir, rel_path)
            os.makedirs(os.path.dirname(target_file_path), exist_ok=True)

            logger.info(f"[{idx}/{len(target_items)}] กำลังดาวน์โหลด: {os.path.basename(rel_path)}...")
            try:
                gdown.download(
                    id=item.id,
                    output=target_file_path,
                    quiet=quiet,
                    resume=True
                )
            except Exception as dl_err:
                logger.error(f"ไม่สามารถดาวน์โหลดไฟล์ {item.path} ได้: {dl_err}")
    else:
        # Fallback กรณี skip_download ใช้งานไม่ได้ ให้โหลดทั้งโฟลเดอร์
        try:
            gdown.download_folder(id=res_id, output=abs_dest_dir, quiet=quiet, use_cookies=False)
        except DownloadError as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ["permission", "anyone with the link", "404", "403"]):
                raise GDrivePermissionError(
                    "ไม่สามารถเข้าถึงโฟลเดอร์ Google Drive ได้ กรุณาตั้งค่าโฟลเดอร์ Google Drive ให้เป็น "
                    "'Anyone with the link can view' (ทุกคนที่มีลิงก์มีสิทธิ์ดู) และตรวจสอบว่า Folder ID ถูกต้อง"
                ) from e
            raise RuntimeError(f"เกิดข้อผิดพลาดในการดาวน์โหลดโฟลเดอร์: {e}") from e

    # 6. แตกไฟล์ ZIP ใดๆ ที่อยู่ใน dest_dir (ถ้ามี)
    for root, _, files in os.walk(abs_dest_dir):
        for f in files:
            file_path = os.path.join(root, f)
            if f.lower().endswith(".zip") or ('.' not in f and zipfile.is_zipfile(file_path)):
                try:
                    with zipfile.ZipFile(file_path, 'r') as z:
                        extract_to = os.path.join(root, os.path.splitext(f)[0])
                        z.extractall(extract_to)
                except Exception as ze:
                    logger.warning(f"ไม่สามารถแตกไฟล์ ZIP {f} ได้: {ze}")

    # 7. ค้นหาและรวบรวมไฟล์ .pdf ทั้งหมดที่ดาวน์โหลดสำเร็จ
    downloaded_pdf_paths: List[str] = []
    for root, _, files in os.walk(abs_dest_dir):
        for f in files:
            if f.lower().endswith(".pdf") and not f.startswith("."):
                downloaded_pdf_paths.append(os.path.abspath(os.path.join(root, f)))

    downloaded_pdf_paths.sort()
    logger.info(f"สรุปผล: พบไฟล์ .pdf พร้อมใช้งานทั้งหมด {len(downloaded_pdf_paths)} ไฟล์")
    return downloaded_pdf_paths


def download_and_extract_pdfs(url_or_id: str, dest_dir: Optional[str] = None) -> List[Tuple[str, str]]:
    """
    ฟังก์ชันเชื่อมต่อสำหรับรองรับ ConsultAI CLD Server เดิม (Backward Compatibility)
    รับ URL/ID แล้วส่งออกผลลัพธ์เป็น [(filename, absolute_file_path), ...]
    """
    if not dest_dir:
        dest_dir = tempfile.mkdtemp(prefix="gdrive_cld_")

    pdf_paths = download_from_gdrive_folder(url_or_id, dest_dir)
    if not pdf_paths:
        raise FileNotFoundError("ดาวน์โหลดเรียบร้อยแต่ไม่พบไฟล์ Drawing PDF ในโฟลเดอร์หรือไฟล์ที่ระบุ")

    return [(os.path.basename(p), p) for p in pdf_paths]


# ==============================================================================
# Standalone Unit & Integration Tests
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("[TEST] เริ่มการทดสอบ Standalone Test สำหรับโมดูล gdrive.py")
    print("=" * 70)

    total_tests = 4
    passed_tests = 0

    # --------------------------------------------------------------------------
    # Test 1: ทดสอบการสกัด Folder ID และ File ID จากลิงก์รูปแบบต่างๆ
    # --------------------------------------------------------------------------
    print("\n[Test 1/4] ตรวจสอบฟังก์ชัน extract_gdrive_folder_id...")
    test_cases = [
        ("https://drive.google.com/drive/folders/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs", ("folder", "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs")),
        ("https://drive.google.com/drive/u/1/folders/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs?usp=sharing", ("folder", "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs")),
        ("https://drive.google.com/open?id=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs", ("folder", "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs")),
        ("https://drive.google.com/file/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs/view", ("file", "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs")),
        ("1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs", ("folder", "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"))
    ]
    t1_success = True
    for url, (expected_type, expected_id) in test_cases:
        res_type, res_id = extract_gdrive_folder_id(url)
        if res_type != expected_type or res_id != expected_id:
            print(f"[FAIL] ผิดพลาด: {url} -> ({res_type}, {res_id}) != ({expected_type}, {expected_id})")
            t1_success = False
            break

    if t1_success:
        passed_tests += 1
        print("[PASS] ผ่านการทดสอบ: สกัด Folder ID และ File ID ถูกต้องแม่นยำทุกรูปแบบ")

    # --------------------------------------------------------------------------
    # Test 2: จัดการ Error กรณี URL หรือ ID ผิดรูปแบบ
    # --------------------------------------------------------------------------
    print("\n[Test 2/4] ตรวจสอบ Error กรณี URL ไม่ถูกต้อง (GDriveInvalidURLError)...")
    try:
        download_from_gdrive_folder("https://invalid-non-drive-link.com/xyz", dest_dir="./temp_test")
        print("[FAIL] ล้มเหลว: ควรเกิด GDriveInvalidURLError แต่กลับผ่าน")
    except GDriveInvalidURLError as e:
        passed_tests += 1
        print("[PASS] ผ่านการทดสอบ: ตรวจจับ URL ไม่ถูกต้องสำเร็จ พร้อมข้อความแจ้งเตือนภาษาไทย:")
        print(f"       รายละเอียด: '{e}'")
    except Exception as e:
        print(f"[FAIL] ผิดประเภท Exception: {type(e)}: {e}")

    # --------------------------------------------------------------------------
    # Test 3: จัดการ Error กรณีโฟลเดอร์ปิดสิทธิ์แชร์ หรือไม่พบ (GDrivePermissionError)
    # --------------------------------------------------------------------------
    print("\n[Test 3/4] ตรวจสอบ Error กรณีโฟลเดอร์ไม่ได้เปิดแชร์ Anyone with the link can view...")
    try:
        # ใช้ ID ที่ไม่มีอยู่จริงเพื่อทดสอบการจับ Error สิทธิ์การเข้าถึง
        download_from_gdrive_folder("https://drive.google.com/drive/folders/1non_existing_private_id_test_9999", dest_dir="./temp_test")
        print("[FAIL] ล้มเหลว: ควรเกิด GDrivePermissionError แต่กลับผ่าน")
    except GDrivePermissionError as e:
        passed_tests += 1
        print("[PASS] ผ่านการทดสอบ: ตรวจจับสิทธิ์การเข้าถึงสำเร็จ พร้อมข้อความภาษาไทยชัดเจน:")
        print(f"       รายละเอียด: '{e}'")
    except Exception as e:
        print(f"[FAIL] ผิดประเภท Exception: {type(e)}: {e}")

    # --------------------------------------------------------------------------
    # Test 4: ทดสอบการทำงานจริง ดาวน์โหลดไฟล์ .pdf จาก Public Google Drive Folder
    # --------------------------------------------------------------------------
    print("\n[Test 4/4] ทดสอบดาวน์โหลดไฟล์ .pdf จริงจาก Public Google Drive Folder...")
    public_folder = "https://drive.google.com/drive/folders/1ZXEhzbLRLU1giKKRJkjm8N04cO_JoYE2"
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # ทดสอบดาวน์โหลดไฟล์ PDF ตัวอย่าง 1 ไฟล์เพื่อความรวดเร็ว
            pdf_results = download_from_gdrive_folder(
                public_folder,
                dest_dir=tmpdir,
                quiet=True,
                max_files=1
            )
            if len(pdf_results) >= 1 and all(p.lower().endswith(".pdf") and os.path.exists(p) for p in pdf_results):
                passed_tests += 1
                sample_pdf = pdf_results[0]
                sample_size = os.path.getsize(sample_pdf)
                print("[PASS] ผ่านการทดสอบ: ดาวน์โหลดไฟล์ PDF สำเร็จ 100%")
                print(f"       รายการไฟล์: {sample_pdf}")
                print(f"       ขนาดไฟล์: {sample_size:,} bytes")
            else:
                print(f"[FAIL] ดาวน์โหลดไม่สำเร็จหรือไม่มีไฟล์ PDF: {pdf_results}")
        except Exception as e:
            print(f"[FAIL] เกิดข้อผิดพลาดขณะดาวน์โหลด: {e}")

    # --------------------------------------------------------------------------
    # สรุปผลการทดสอบทั้งหมด
    # --------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print(f"[SUMMARY] ผลการทดสอบทั้งหมด: ผ่าน {passed_tests}/{total_tests} ข้อ")
    if passed_tests == total_tests:
        print("[SUCCESS] ทุกการทดสอบผ่านฉลุย 100% โมดูลพร้อมใช้งานในระบบ ConsultAI ได้ทันที!")
    else:
        print("[WARN] มีบางการทดสอบไม่ผ่าน กรุณาตรวจสอบ")
    print("=" * 70)
