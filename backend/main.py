from backend import db_health
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Веб-отчётность", version="0.1.0")

class DataLogin(BaseModel):
    pass


class DataUpload(BaseModel):
    num: int # 1
    direction: str # 2
    tech_center: str # 3
    category: int # 4
    network_type: int # 5
    network_element: str # 6
    total_base_station: int # 7
    element_type: str # 8
    type: str # 9
    description: str # 10
    start_time: str # 11
    end_time: str # 12
    lifetime_by_battery: str # 13
    lifetime_by_generator: str # 14
    time_accident: str # 15
    time_connection_interupt: str # 16
    base_station_downtime: str # 17
    accident_comment: str # 18
    accident_detailed_description: str # 19

@app.get("/check")
def health_check():
    raise HTTPException(status_code=200, detail=f'API is up and ready to go! DB status: {db_health()}')

@app.get('/Accident')
def data_tranfer():
    pass
