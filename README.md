# NABI Scout Web v0.1

Independent investment research application built with Streamlit and Supabase.

## Local run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Copy `.streamlit/secrets.example.toml` to `.streamlit/secrets.toml` and fill in the Supabase values.

## Security note

The starter SQL includes temporary anonymous policies for first deployment testing.
Add authentication and remove the temporary anonymous policies before using the app with sensitive or private data.
