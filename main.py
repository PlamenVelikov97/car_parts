import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from supabase import create_client, Client
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="Auto Parts Inventory API")

# Разрешаваме достъп от мобилни устройства (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/ui")
def get_ui():
  return FileResponse("index.html")

# Вземане на всички складове за падащото меню
@app.get("/warehouses/")
def get_warehouses():
  response = supabase.table("warehouses").select("*").execute()
  return response.data

# 1. Вземане на всички складове (за падащото меню)
@app.get("/warehouses/")
def get_warehouses():
  response = supabase.table("warehouses").select("*").execute()
  return response.data


# 2. Вземане на всички коли + техния финансов баланс
@app.get("/cars/summary")
def get_cars_summary():
  cars_res = supabase.table("cars").select("*").execute()
  cars = cars_res.data

  for car in cars:
    # Вземаме всички части за тази кола
    parts_res = (
        supabase.table("parts")
        .select("price, sold_price, status")
        .eq("car_id", car["id"])
        .execute()
    )
    parts = parts_res.data

    # Изчисляваме приходите
    total_parts_price = sum(p["price"] for p in parts)
    total_sales = sum(
        p["sold_price"]
        for p in parts
        if p["status"] == "Продадено" and p["sold_price"]
    )
    net_profit = total_sales - car["purchase_price"]

    car["total_parts_val"] = total_parts_price
    car["total_sales"] = total_sales
    car["net_profit"] = net_profit
    car["parts_count"] = len(parts)

  return cars

