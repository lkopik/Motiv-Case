from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, field_validator, Field

app = FastAPI(title="Веб-отчётность", version="0.1.0")

direct = ['ХМЯН', 'СВН', 'ЮЗН', 'Вся сеть']

class DataLogin(BaseModel):
    pass


class DataUpload(BaseModel):
    device_num: str | None = Field(None, max_length=15) # №1
    direction: str | None = Field(None, max_length=8) # №2
    tech_center: str | None = Field(None, max_length=4) # №3
    category: str | None = Field(None, max_length=1) # №4
    network_type: str | None = Field(None, max_length=7)# №5
    network_element: str | None = Field(None, max_length=20) # №6
    total_base_station: str | None = Field(None, max_length=10000) # №7
    element_type: str | None = Field(None, max_length=255) # №8
    type: str | None = Field(None, max_length=5) # №9
    description: str | None = Field(None, max_length=255) # №10
    start_time: str | None = Field(None, max_length=50) # №11
    end_time: str | None = Field(None, max_length=50) # №12
    lifetime_by_battery: str | None = Field(None, max_length=8) # №13
    lifetime_by_generator: str | None = Field(None, max_length=8) # №14
    time_accident: str | None = Field(None, max_length=8) # №15 !!!ПОМЕНЯТЬ НА ФОРМУЛУ ПО ТЗ!!!
    time_connection_interupt: str | None = Field(None, max_length=8) # №16
    base_station_downtime: str | None = Field(None, max_length=8) # №17 !!!ПОМЕНЯТЬ НА ФОРМУЛУ ПО ТЗ!!!
    accident_comment: str | None = Field(None, max_length=20) # №18
    accident_detailed_description: str | None = Field(None, max_length=255) # №19

    @field_validator('category')
    def num_is_digit(cls, v: str) -> str | None:
        try:
            if 0 < int(v) < 4:
                return v
            raise ValueError('Категория должна быть числом от 1 до 3')
        except:
            raise ValueError('Ошибка. Введенное значение должно быть числом')

    @field_validator('device_num')
    def aaa(self):
        pass




@app.get("/check")
def health_check():
    raise HTTPException(status_code=200, detail=f'API работает!')

@app.get('/Accident')
def data_tranfer():
    pass
