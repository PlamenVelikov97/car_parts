import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from supabase import Client, create_client

app = FastAPI(title="Auto Parts Inventory API")

# Разрешаваме достъп от мобилни устройства (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Данни за връзка с Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

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
  status: str = "На колата"
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


# 1. Складове (за падащото меню)
@app.get("/warehouses/")
def get_warehouses():
  response = supabase.table("warehouses").select("*").execute()
  return response.data


# 2. Вземане на коли + Финансов баланс
@app.get("/cars/summary")
def get_cars_summary():
  cars_res = supabase.table("cars").select("*").execute()
  cars = cars_res.data

  for car in cars:
    parts_res = (
        supabase.table("parts")
        .select("price, sold_price, status")
        .eq("car_id", car["id"])
        .execute()
    )
    parts = parts_res.data

    total_parts_price = sum(p["price"] for p in parts if p.get("price"))
    total_sales = sum(
        p["sold_price"]
        for p in parts
        if p.get("status") == "Продадено" and p.get("sold_price")
    )
    net_profit = total_sales - car["purchase_price"]

    car["total_parts_val"] = total_parts_price
    car["total_sales"] = total_sales
    car["net_profit"] = net_profit
    car["parts_count"] = len(parts)

  return cars


# 3. Добавяне на нова кола-донор
@app.post("/cars/")
def create_car(car: CarCreate):
  response = supabase.table("cars").insert(car.dict()).execute()
  return response.data


# 4. Добавяне на нова част
@app.post("/parts/")
def create_part(part: PartCreate):
  response = supabase.table("parts").insert(part.dict()).execute()
  return response.data


# 5. Търсачка за части
@app.get("/parts/search")
def search_parts(q: str = Query(..., min_length=2)):
  response = (
      supabase.table("parts")
      .select("*, warehouses(name), cars(title)")
      .or_(
          f"title.ilike.%{q}%,oem_number.ilike.%{q}%,compatible_models.ilike.%{q}%"
      )
      .execute()
  )
  return response.data


# 6. Продажба на част
@app.put("/parts/{part_id}/sell")
def sell_part(part_id: int, sell_data: PartSell):
  update_data = {"status": "Продадено", "sold_price": sell_data.sold_price}
  response = (
      supabase.table("parts").update(update_data).eq("id", part_id).execute()
  )
  return response.data


# 7. Отваряне на мобилния HTML
@app.get("/ui")
def get_ui():
  return FileResponse("index.html")
