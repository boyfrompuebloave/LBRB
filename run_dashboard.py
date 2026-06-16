import subprocess
import time
import os

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

URL = "http://localhost:8501"

chrome = next((p for p in CHROME_PATHS if os.path.exists(p)), None)
if not chrome:
    raise FileNotFoundError("Chrome을 찾을 수 없습니다.")

dashboard_dir = os.path.dirname(os.path.abspath(__file__))
subprocess.Popen(
    ["py", "-m", "streamlit", "run", "dashboard.py"],
    cwd=dashboard_dir,
)

time.sleep(3)
subprocess.Popen([chrome, URL])
print(f"Chrome으로 {URL} 열었습니다.")
