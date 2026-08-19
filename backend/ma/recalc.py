"""
Workbook recalculation helper for the M&A modeling tool.

openpyxl does NOT compute formulas — reading a generated file back gives
None for every formula cell. All verification must run the workbook
through a real spreadsheet engine (LibreOffice headless preferred, Excel
COM fallback on Windows) and read back with data_only=True. Never trust
formula strings or a parallel hand calculation as ground truth.

Ported from AIO LBO (/reference/backend/report_generator.py, Part 1).
"""

import os
import sys
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Optional


def find_libreoffice_executable() -> Optional[str]:
    """Find the LibreOffice executable on the system."""
    for cmd in ['soffice', 'libreoffice']:
        path = shutil.which(cmd)
        if path:
            return path

    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/lib/libreoffice/program/soffice",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def recalculate_workbook_excel_com(filepath: str) -> str:
    """
    Recalculate a workbook using Excel COM on Windows (fallback when
    LibreOffice is unavailable). Returns path to recalculated temp file.
    """
    if sys.platform != 'win32':
        raise RuntimeError("Excel COM automation only available on Windows")

    try:
        import win32com.client
    except ImportError:
        raise RuntimeError(
            "pywin32 not installed. Run: pip install pywin32\n"
            "Or install LibreOffice for cross-platform support."
        )

    temp_dir = tempfile.mkdtemp(prefix="mna_recalc_")
    input_name = Path(filepath).stem
    output_path = os.path.join(temp_dir, f"{input_name}.xlsx")

    excel = None
    wb = None

    try:
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        wb = excel.Workbooks.Open(os.path.abspath(filepath))
        wb.Application.CalculateFull()
        wb.SaveAs(os.path.abspath(output_path), FileFormat=51)  # 51 = xlsx

        return output_path

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Excel COM recalculation failed: {e}")

    finally:
        if wb:
            wb.Close(SaveChanges=False)
        if excel:
            excel.Quit()


def recalculate_workbook(filepath: str, allow_excel_fallback: bool = True) -> str:
    """
    Recalculate a workbook via LibreOffice headless (--convert-to xlsx
    forces recalculation during the save). Returns path to the
    recalculated temporary file. Raises RuntimeError if no engine exists.
    """
    lo_path = find_libreoffice_executable()

    if not lo_path:
        if allow_excel_fallback and sys.platform == 'win32':
            print("  LibreOffice not found, trying Excel COM...")
            return recalculate_workbook_excel_com(filepath)

        raise RuntimeError(
            "No spreadsheet engine found for recalculation.\n"
            "Install LibreOffice (soffice on PATH), or on Windows with "
            "Excel: pip install pywin32."
        )

    temp_dir = tempfile.mkdtemp(prefix="mna_recalc_")

    try:
        result = subprocess.run(
            [lo_path, "--headless", "--convert-to", "xlsx",
             "--outdir", temp_dir, filepath],
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed (exit code {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

        input_name = Path(filepath).stem
        output_path = os.path.join(temp_dir, f"{input_name}.xlsx")

        if not os.path.isfile(output_path):
            raise RuntimeError(
                f"LibreOffice did not produce expected output: {output_path}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

        return output_path

    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("LibreOffice recalculation timed out")
