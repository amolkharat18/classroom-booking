$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "C:\amol\Projects\classroom-booking\codex"
$py = "C:\Users\amolk\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m streamlit run app.py --server.headless true --server.port 8501 --server.address 127.0.0.1
