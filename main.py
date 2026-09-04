import os
import json
import base64
import httpx
from typing import List, Optional
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# === ИНИЦИАЛИЗАЦИЯ НА FASTAPI И JINJA2 ===
app = FastAPI(title="Автоморга Мениджър")
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# === НАСТРОЙКИ НА ВЪНШНИ УСЛУГИ ===
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL", "")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Свързване с Supabase
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Свързване с Cloudinary
if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)
elif CLOUDINARY_CLOUD_NAME:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=os.getenv("CLOUDINARY_API_KEY", ""),
        api_secret=os.getenv("CLOUDINARY_API_SECRET", "")
    )


# === PYDANTIC МОДЕЛИ ===
class WarehouseCreate(BaseModel):
    name: str
    address: Optional[str] = None

class CarCreate(BaseModel):
    make: str
    model: str
    year: Optional[int] = None
    engine: Optional[str] = None
    fuel_type: Optional[str] = None
    purchase_price: float = 0.0
    warehouse_id: Optional[int] = None
    notes: Optional[str] = None
    photo_urls: Optional[List[str]] = []
    created_at: Optional[str] = None

class CarScrap(BaseModel):
    scrap_price: float = 0.0
    scrapped_at: Optional[str] = None

class PartCreate(BaseModel):
    title: str
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    oem_number: Optional[str] = None
    price: Optional[float] = 0.0
    sold_price: Optional[float] = 0.0
    status: Optional[str] = "Наличен"
    warehouse_id: Optional[int] = None
    car_id: Optional[int] = None
    notes: Optional[str] = None
    photo_urls: Optional[List[str]] = []
    created_at: Optional[str] = None

class PartUpdate(BaseModel):
    title: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    oem_number: Optional[str] = None
    price: Optional[float] = None
    sold_price: Optional[float] = None
    status: Optional[str] = None
    warehouse_id: Optional[int] = None
    car_id: Optional[int] = None
    notes: Optional[str] = None
    photo_urls: Optional[List[str]] = None
    created_at: Optional[str] = None
    sold_at: Optional[str] = None

class PartSell(BaseModel):
    sold_price: float = 0.0
    sold_at: Optional[str] = None

class AiAnalyzeRequest(BaseModel):
    photo_url: str
    type: str  # 'car' или 'part'


# === ВЕРИФИКАЦИЯ НА SUPABASE ===
def check_db():
    if not supabase:
        raise HTTPException(status_code=500, detail="Липсва връзка с Supabase база данни.")


# === HTML РЕНДЕРИРАНЕ ===
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


# === 1. СКЛАДОВЕ ===
@app.get("/warehouses")
def get_warehouses():
    check_db()
    res = supabase.table("warehouses").select("*").order("id").execute()
    return res.data

@app.post("/warehouses")
def create_warehouse(wh: WarehouseCreate):
    check_db()
    data = wh.model_dump() if hasattr(wh, "model_dump") else wh.dict()
    res = supabase.table("warehouses").insert(data).execute()
    return res.data

@app.put("/warehouses/{wh_id}")
def update_warehouse(wh_id: int, wh: WarehouseCreate):
    check_db()
    data = wh.model_dump() if hasattr(wh, "model_dump") else wh.dict()
    res = supabase.table("warehouses").update(data).eq("id", wh_id).execute()
    return res.data

@app.delete("/warehouses/{wh_id}")
def delete_warehouse(wh_id: int):
    check_db()
    res = supabase.table("warehouses").delete().eq("id", wh_id).execute()
    return {"message": "Warehouse deleted"}


# === 2. КОЛИ-ДОНОРИ ===
@app.get("/cars")
def get_cars():
    check_db()
    res = supabase.table("cars").select("*, warehouses(name)").order("created_at", desc=True).execute()
    return res.data

@app.get("/cars/summary")
def get_cars_summary():
    # Взимаме колите + името на склада чрез Supabase Join Syntax
    response = supabase.table("cars").select("*, warehouses(id, name), parts(sold_price, status)").execute()
    cars = response.data
    
    # Форматираме резултата, за да може JS да го чете лесно
    result = []
    for car in cars:
        # Изчисляваме общите продажби на части за тази кола
        parts = car.get("parts", [])
        total_parts_sold = sum(
            float(p.get("sold_price") or 0) 
            for p in parts 
            if p.get("status") and "продад" in p.get("status").lower()
        )
        
        car_data = dict(car)
        car_data["total_parts_sold"] = total_parts_sold
        result.append(car_data)
        
    return result

@app.post("/cars")
def create_car(car: CarCreate):
    check_db()
    try:
        car_data = car.model_dump() if hasattr(car, "model_dump") else car.dict()
        car_data["title"] = f"{car.make} {car.model}".strip()
        if not car_data.get("created_at"):
            car_data["created_at"] = datetime.now(timezone.utc).isoformat()
        
        res = supabase.table("cars").insert(car_data).execute()
        return res.data
    except Exception as e:
        print(f"Error creating car: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при запис на кола: {str(e)}")

@app.put("/cars/{car_id}")
def update_car(car_id: int, car: CarCreate):
    check_db()
    try:
        car_data = car.model_dump() if hasattr(car, "model_dump") else car.dict()
        res = supabase.table("cars").update(car_data).eq("id", car_id).execute()
        return res.data
    except Exception as e:
        print(f"Error updating car: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при редакция на кола: {str(e)}")

@app.put("/cars/{car_id}/scrap")
def scrap_car(car_id: int, scrap: CarScrap):
    check_db()
    try:
        scrapped_time = scrap.scrapped_at or datetime.now(timezone.utc).isoformat()
        data = {
            "status": "Скрап",
            "scrap_price": scrap.scrap_price,
            "scrapped_at": scrapped_time
        }
        res = supabase.table("cars").update(data).eq("id", car_id).execute()
        return res.data
    except Exception as e:
        print(f"Error scraping car: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при скрапиране: {str(e)}")

@app.delete("/cars/{car_id}")
def delete_car(car_id: int):
    check_db()
    supabase.table("parts").update({"car_id": None}).eq("car_id", car_id).execute()
    res = supabase.table("cars").delete().eq("id", car_id).execute()
    return {"message": "Car deleted"}


# === 3. АВТОЧАСТИ ===
@app.get("/parts/search")
def search_parts(
    q: Optional[str] = None,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    check_db()
    try:
        query = supabase.table("parts").select("*, warehouses(name), cars(make, model)").order("created_at", desc=True)
        
        if q:
            query = query.or_(f"title.ilike.%{q}%,make.ilike.%{q}%,model.ilike.%{q}%,oem_number.ilike.%{q}%")
        
        if status:
            query = query.eq("status", status)

        # При филтриране на продадени се взема sold_at, за налични — created_at
        date_field = "sold_at" if status == "Продадено" else "created_at"
        if start_date:
            query = query.gte(date_field, f"{start_date}T00:00:00")
        if end_date:
            query = query.lte(date_field, f"{end_date}T23:59:59")

        res = query.execute()
        return res.data or []
    except Exception as e:
        print(f"Error in /parts/search: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при търсене на части: {str(e)}")

@app.post("/parts")
def create_part(part: PartCreate):
    check_db()
    try:
        part_data = part.model_dump() if hasattr(part, "model_dump") else part.dict()
        if not part_data.get("status"):
            part_data["status"] = "Наличен"
        if not part_data.get("created_at"):
            part_data["created_at"] = datetime.now(timezone.utc).isoformat()
            
        res = supabase.table("parts").insert(part_data).execute()
        return res.data
    except Exception as e:
        print(f"Error creating part: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при запис на част: {str(e)}")

@app.put("/parts/{part_id}")
def update_part(part_id: int, part: PartUpdate):
    check_db()
    try:
        update_data = part.model_dump(exclude_unset=True) if hasattr(part, "model_dump") else part.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="Няма предоставени данни за промяна.")

        res = supabase.table("parts").update(update_data).eq("id", part_id).execute()
        return res.data
    except Exception as e:
        print(f"Error updating part {part_id}: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при обновяване на част: {str(e)}")

@app.put("/parts/{part_id}/sell")
def sell_part(part_id: int, sell: PartSell):
    check_db()
    try:
        sold_time = sell.sold_at or datetime.now(timezone.utc).isoformat()
        data = {
            "status": "Продадено",
            "sold_price": sell.sold_price,
            "sold_at": sold_time
        }
        res = supabase.table("parts").update(data).eq("id", part_id).execute()
        return res.data
    except Exception as e:
        print(f"Error selling part: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при продажба: {str(e)}")

@app.delete("/parts/{part_id}")
def delete_part(part_id: int):
    check_db()
    res = supabase.table("parts").delete().eq("id", part_id).execute()
    return {"message": "Part deleted"}


# === 4. КАЧВАНЕ НА СНИМКИ (CLOUDINARY) ===
@app.post("/upload-photos")
def upload_photos(files: List[UploadFile] = File(...)):
    if not (CLOUDINARY_URL or CLOUDINARY_CLOUD_NAME):
        raise HTTPException(status_code=500, detail="Cloudinary не е конфигуриран на сървъра.")

    uploaded_urls = []
    for file in files:
        try:
            content = file.file.read()
            res = cloudinary.uploader.upload(content)
            if "secure_url" in res:
                uploaded_urls.append(res["secure_url"])
        except Exception as e:
            print(f"Cloudinary error: {e}", flush=True)
            raise HTTPException(status_code=500, detail=f"Грешка при качване в Cloudinary: {str(e)}")

    return {"photo_urls": uploaded_urls}


# === 5. AI АНАЛИЗ НА СНИМКИ ===
@app.post("/ai-analyze")
async def ai_analyze(req: AiAnalyzeRequest):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY is missing!", flush=True)
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY липсва в Render Environment.")

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            img_res = await client.get(req.photo_url)
            if img_res.status_code != 200:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Снимката не може да бъде свалена от Cloudinary (Код: {img_res.status_code})"
                )

            image_bytes = img_res.content
            mime_type = img_res.headers.get("Content-Type", "image/jpeg")
            if "image" not in mime_type:
                mime_type = "image/jpeg"

            base64_image = base64.b64encode(image_bytes).decode("utf-8")

        if req.type == "car":
            prompt_text = (
                "Анализирай това изображение на автомобил и върни САМО валиден JSON обект "
                "без markdown форматиране със следните полета: "
                "'make' (Марка), 'model' (Модел), 'year' (Година като число или null), "
                "'engine' (Двигател), 'fuel_type' (Дизел/Бензин/Хибрид/Електрически)."
            )
        else:
            prompt_text = (
                "Анализирай това изображение на авточаст и върни САМО валиден JSON обект "
                "без markdown форматиране със следните полета: "
                "'title' (Име на частта), 'make' (Марка), 'model' (Модел), "
                "'year' (Година като число или null), 'oem_number' (OEM номер или null)."
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            api_res = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            
            if api_res.status_code != 200:
                print(f"Google API Error ({api_res.status_code}): {api_res.text}", flush=True)
                raise HTTPException(
                    status_code=api_res.status_code, 
                    detail=f"Грешка от Google API ({api_res.status_code}): {api_res.text}"
                )

            res_data = api_res.json()
            raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()

            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text.rsplit("\n", 1)[0]
                raw_text = raw_text.replace("json", "").strip()

            return {"result": json.loads(raw_text)}

    except json.JSONDecodeError:
        print(f"JSON Parsing Error. Raw text was: {raw_text}", flush=True)
        raise HTTPException(status_code=500, detail="AI върна текст, който не може да бъде разпознат като JSON.")
    except Exception as e:
        print(f"Unhandled Exception in /ai-analyze: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка AI Анализ: {str(e)}")


# === 6. ФИНАНСОВИ РЕЗУЛТАТИ С ФИЛТЪР ПО ДАТИ ===
@app.get("/reports/financials")
def get_financials(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None)
):
    check_db()
    
    # 1. Покупки на коли за периода
    cars_query = supabase.table("cars").select("purchase_price, scrap_price, status, created_at, scrapped_at")
    if start_date:
        cars_query = cars_query.gte("created_at", f"{start_date}T00:00:00")
    if end_date:
        cars_query = cars_query.lte("created_at", f"{end_date}T23:59:59")
    cars = cars_query.execute().data or []

    # 2. Продажби на части за периода
    parts_query = supabase.table("parts").select("price, sold_price, status, created_at, sold_at").eq("status", "Продадено")
    if start_date:
        parts_query = parts_query.gte("sold_at", f"{start_date}T00:00:00")
    if end_date:
        parts_query = parts_query.lte("sold_at", f"{end_date}T23:59:59")
    parts = parts_query.execute().data or []

    # 3. Изчисление на финансовите суми
    total_car_investment = sum(float(c.get("purchase_price") or 0.0) for c in cars)
    total_parts_sales = sum(float(p.get("sold_price") or 0.0) for p in parts)
    total_scrap_sales = sum(float(c.get("scrap_price") or 0.0) for c in cars if c.get("status") == "Скрап")
    
    total_income = total_parts_sales + total_scrap_sales
    net_profit = total_income - total_car_investment

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_car_investment": total_car_investment,
        "total_parts_sales": total_parts_sales,
        "total_scrap_sales": total_scrap_sales,
        "total_income": total_income,
        "net_profit": net_profit,
        "cars_count": len(cars),
        "parts_sold_count": len(parts)
    }
