from fastapi import FastAPI, HTTPException

app = FastAPI(title="Веб-отчётность", version="0.1.0")

@app.get("/health/api")
def health_check():
    raise HTTPException(status_code=200, detail='The API is up and ready to go!')

