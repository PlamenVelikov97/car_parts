import os
import uuid
from typing import Optional
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from supabase import Client, create_client

app = FastAPI(title="Auto Parts Inventory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


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


@app.get("/")
def home():
  return {"message": "API е онлайн!"}


@app.get("/warehouses/")
def get_warehouses():
  res = supabase.table("warehouses").select("*").execute()
  return res.data or []


@app.get("/cars/summary")
def get_cars_summary():
  cars_res = supabase.table("cars").select("*").execute()
  cars = cars_res.data or []

  for car in cars:
    parts_res = (
        supabase.table("parts")
        .select("price, sold_price, status")
        .eq("car_id", car["id"])
        .execute()
    )
    parts = parts_res.data or []

    total_parts_price = sum(
        float(p.get("price") or 0) for p in parts if p.get("price") is not None
    )
    total_sales = sum(
        float(p.get("sold_price") or 0)
        for p in parts
        if p.get("status") == "Продадено" and p.get("sold_price") is not None
    )

    purchase_price = float(car.get("purchase_price") or 0)
    net_profit = total_sales - purchase_price

    car["total_parts_val"] = total_parts_price
    car["total_sales"] = total_sales
    car["net_profit"] = net_profit
    car["parts_count"] = len(parts)

  return cars


@app.post("/cars/")
def create_car(car: CarCreate):
  res = supabase.table("cars").insert(car.dict()).execute()
  return res.data


@app.post("/upload-photo/")
async def upload_photo(file: UploadFile = File(...)):
  try:
    file_bytes = await file.read()
    file_ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    file_name = f"{uuid.uuid4()}.{file_ext}"

    res = supabase.storage.from_("parts-photos").upload(
        file_name, file_bytes, {"content-type": file.content_type}
    )

    public_url = supabase.storage.from_("parts-photos").get_public_url(
        file_name
    )
    return {"photo_url": public_url}
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при качване на снимка: {str(e)}"
    )


@app.post("/parts/")
def create_part(part: PartCreate):
  res = supabase.table("parts").insert(part.dict()).execute()
  return res.data


# КОРИГИРАНО ТЪРСЕНЕ
@app.get("/parts/search")
def search_parts(q: str = Query(..., min_length=2)):
  res = (
      supabase.table("parts")
      .select("*")
      .or_(f"title.ilike.%{q}%,oem_number.ilike.%{q}%")
      .execute()
  )
  return res.data or []


@app.put("/parts/{part_id}/sell")
def sell_part(part_id: int, sell_data: PartSell):
  update_data = {"status": "Продадено", "sold_price": sell_data.sold_price}
  res = supabase.table("parts").update(update_data).eq("id", part_id).execute()
  return res.data


@app.get("/ui")
def get_ui():
  if not os.path.exists("index.html"):
    raise HTTPException(status_code=404, detail="index.html не е намерен")
  return FileResponse("index.html")
