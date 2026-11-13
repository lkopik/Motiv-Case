from backend import db_health
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Веб-отчётность", version="0.1.0")

class DataUpload(BaseModel):
    num: int
    direction: str
    TC: str
    category: int
    connection_type: int
    connection_element: str
    total_base_station: int
    type: str
    description: str

@app.get("/health")
def health_check():
    raise HTTPException(status_code=200, detail=f'API is up and ready to go! DB status: {db_health()}')

@app.get('Аварии')
def