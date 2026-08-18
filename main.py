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

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


class WarehouseCreate(BaseModel):
  name: str
  address: Optional[str] = None


class CarCreate(BaseModel):
  make: str
  model: str
  purchase_price: float
  warehouse_id: Optional[int] = None


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


def to_dict(model: BaseModel) -> dict:
  if hasattr(model, "model_dump"):
    return model.model_dump()
  return model.dict()


@app.get("/")
@app.get("/ui")
def get_ui():
  if not os.path.exists("index.html"):
    raise HTTPException(status_code=404, detail="index.html не е намерен")
  return FileResponse("index.html")


# --- СКЛАДОВЕ ---


@app.get("/warehouses")
@app.get("/warehouses/")
def get_warehouses():
  try:
    res = supabase.table("warehouses").select("*").execute()
    return res.data or []
  except Exception as e:
    print("Грешка при четене на складове:", e)
    return []


@app.post("/warehouses")
@app.post("/warehouses/")
def create_warehouse(wh: WarehouseCreate):
  try:
    data = to_dict(wh)
    res = supabase.table("warehouses").insert(data).execute()
    return res.data
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при създаване на склад: {str(e)}"
    )


@app.put("/warehouses/{wh_id}")
def update_warehouse(wh_id: int, wh: WarehouseCreate):
  try:
    data = to_dict(wh)
    res = supabase.table("warehouses").update(data).eq("id", wh_id).execute()
    return res.data
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при редакция на склад: {str(e)}"
    )


@app.delete("/warehouses/{wh_id}")
def delete_warehouse(wh_id: int):
  try:
    res = supabase.table("warehouses").delete().eq("id", wh_id).execute()
    return {"message": "Складът е изтрит успешно", "data": res.data}
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при изтриване на склад: {str(e)}"
    )


# --- КОЛИ ---


@app.get("/cars/summary")
@app.get("/cars/summary/")
def get_cars_summary():
  try:
    # Зареждаме колите заедно със свързания склад (warehouses)
    cars_res = supabase.table("cars").select("*, warehouses(*)").execute()
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
          float(p.get("price") or 0)
          for p in parts
          if p.get("price") is not None
      )
      total_sales = sum(
          float(p.get("sold_price") or 0)
          for p in parts
          if p.get("status") == "Продадено" and p.get("sold_price") is not None
      )

      purchase_price = float(car.get("purchase_price") or 0)
      net_profit = total_sales - purchase_price

      car_title = (
          f"{car.get('make', '')} {car.get('model', '')}".strip()
          or car.get("title")
          or "Без име"
      )
      car["title"] = car_title
      car["total_parts_val"] = total_parts_price
      car["total_sales"] = total_sales
      car["net_profit"] = net_profit
      car["parts_count"] = len(parts)

    return cars
  except Exception as e:
    print("Грешка при коли summary:", e)
    return []


@app.post("/cars")
@app.post("/cars/")
def create_car(car: CarCreate):
  try:
    data = to_dict(car)
    data["title"] = f"{car.make} {car.model}"
    res = supabase.table("cars").insert(data).execute()
    return res.data
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при добавяне на кола: {str(e)}"
    )


@app.put("/cars/{car_id}")
def update_car(car_id: int, car: CarCreate):
  try:
    data = to_dict(car)
    data["title"] = f"{car.make} {car.model}"
    res = supabase.table("cars").update(data).eq("id", car_id).execute()
    return res.data
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при редакция на кола: {str(e)}"
    )


@app.delete("/cars/{car_id}")
def delete_car(car_id: int):
  try:
    res = supabase.table("cars").delete().eq("id", car_id).execute()
    return {"message": "Колата е изтрита успешно", "data": res.data}
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при изтриване на кола: {str(e)}"
    )


# --- ЧАСТИ & СНИМКИ ---


@app.post("/upload-photo")
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


@app.post("/parts")
@app.post("/parts/")
def create_part(part: PartCreate):
  try:
    data = to_dict(part)
    res = supabase.table("parts").insert(data).execute()
    return res.data
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при създаване на част: {str(e)}"
    )


@app.get("/parts/search")
def search_parts(q: Optional[str] = Query(None)):
  try:
    # Зареждаме частите заедно с колата и склада на колата (cars(*, warehouses(*)))
    res = supabase.table("parts").select("*, cars(*, warehouses(*))").execute()
    return res.data or []
  except Exception as e:
    print("Грешка при търсене на части:", e)
    return []


@app.put("/parts/{part_id}/sell")
def sell_part(part_id: int, sell_data: PartSell):
  try:
    update_data = {"status": "Продадено", "sold_price": sell_data.sold_price}
    res = (
        supabase.table("parts").update(update_data).eq("id", part_id).execute()
    )
    return res.data
  except Exception as e:
    raise HTTPException(
        status_code=500, detail=f"Грешка при продажба: {str(e)}"
    )
