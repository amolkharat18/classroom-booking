# Classroom Booking Streamlit App

A Streamlit app for booking classrooms with local SQLite storage, admin-managed users, holidays, room colors, calendar views, recurrence, analytics, and an OpenAI-powered chat assistant.

## Run Locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

On first launch, the app asks you to create the first admin user.

## Secrets

For local development, set `OPENAI_API_KEY` in your environment or in `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "..."
```

Do not commit `.streamlit/secrets.toml`.

For Streamlit Community Cloud, paste the same secret in the app's advanced settings.
`r`n
## Tests

```powershell
pytest
```
