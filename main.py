import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="Auto Parts Inventory API")

# Данни за връзка с Supabase (взимат се от 환경 променливи)
SUPABASE_URL = os.getenv("SUPABASE_URL", "ТВОЯТ_SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "ТВОЯТ_SUPABASE_ANON_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Pydantic Схеми за валидация ---
class CarCreate(BaseModel):
    title: str
    purchase_price: float
    warehouse_id: int

class PartCreate(BaseModel):
    title: str
    oem_number: Optional[str] = None
    compatible_models: Optional[str] = None
    price: float
    status: str = "На колата"  # 'На колата', 'На рафт', 'Продадено'
    shelf_location: Optional[str] = None
    car_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    photo_url: Optional[str] = None

class PartSell(BaseModel):
    sold_price: float

# --- Маршрути (Endpoints) ---

@app.get("/")
def home():
    return {"message": "Auto Parts Inventory API е онлайн!"}

# 1. Добавяне на нова кола-донор
@app.post("/cars/")
def create_car(car: CarCreate):
    response = supabase.table("cars").insert(car.dict()).execute()
    return response.data

# 2. Финансова справка за кола ($+ / -$)
@app.get("/cars/{car_id}/financials")
def get_car_financials(car_id: int):
    # Взимаме колата
    car_res = supabase.table("cars").select("*").eq("id", car_id).execute()
    if not car_res.data:
        raise HTTPException(status_code=404, detail="Колата не е намерена")
    
    car = car_res.data[0]
    investment = float(car["purchase_price"])
    
    # Изчисляваме сумата от продадените части
    parts_res = supabase.table("parts").select("sold_price").eq("car_id", car_id).eq("status", "Продадено").execute()
    
    total_sales = sum([float(p["sold_price"] or 0) for p in parts_res.data])
    balance = total_sales - investment
    
    return {
        "car_title": car["title"],
        "investment": investment,
        "total_sales": total_sales,
        "balance": balance,
        "is_profitable": balance >= 0
    }

# 3. Добавяне на нова част
@app.post("/parts/")
def create_part(part: PartCreate):
    response = supabase.table("parts").insert(part.dict()).execute()
    return response.data

# 4. Търсачка (по име, OEM номер или модел)
@app.get("/parts/search")
def search_parts(q: str = Query(..., min_length=2)):
    # Търси съвпадения в title, oem_number или compatible_models
    response = supabase.table("parts").select("*, warehouses(name), cars(title)").or_(
        f"title.ilike.%{q}%,oem_number.ilike.%{q}%,compatible_models.ilike.%{q}%"
    ).execute()
    return response.data

# 5. Продажба на част
@app.put("/parts/{part_id}/sell")
def sell_part(part_id: int, sell_data: PartSell):
    update_data = {
        "status": "Продадено",
        "sold_price": sell_data.sold_price
    }
    response = supabase.table("parts").update(update_data).eq("id", part_id).execute()
    return response.data