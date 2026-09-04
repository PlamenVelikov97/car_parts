import os
import json
import base64
import httpx
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Request
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

class CarScrap(BaseModel):
    scrap_price: float = 0.0

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

class PartSell(BaseModel):
    sold_price: float = 0.0

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
    res = supabase.table("cars").select("*, warehouses(name)").order("id", desc=True).execute()
    return res.data

@app.get("/cars/summary")
def get_cars_summary():
    check_db()
    try:
        cars_res = supabase.table("cars").select("*, warehouses(name)").order("id", desc=True).execute()
        cars = cars_res.data or []

        parts_res = supabase.table("parts").select("id, car_id, title, status, price, sold_price").execute()
        parts = parts_res.data or []

        result = []
        for car in cars:
            car_parts = [p for p in parts if p and p.get("car_id") == car.get("id")]
            
            sold_parts_sum = sum(
                float(p.get("sold_price") or 0.0) 
                for p in car_parts 
                if p.get("status") and "продад" in str(p.get("status")).lower()
            )
            
            scrap_price = float(car.get("scrap_price") or 0.0)
            purchase = float(car.get("purchase_price") or 0.0)
            
            total_sales = sold_parts_sum + scrap_price
            net_profit = total_sales - purchase

            car_data = dict(car)
            car_data["parts"] = car_parts
            car_data["parts_count"] = len(car_parts)
            car_data["total_sales"] = total_sales
            car_data["net_profit"] = net_profit
            
            make = car.get("make") or ""
            model = car.get("model") or ""
            car_data["title"] = car.get("title") or f"{make} {model}".strip() or "Без име"
            
            result.append(car_data)

        return result
    except Exception as e:
        print(f"Error in /cars/summary: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка при извличане на колите: {str(e)}")

@app.post("/cars")
def create_car(car: CarCreate):
    check_db()
    try:
        car_data = car.model_dump() if hasattr(car, "model_dump") else car.dict()
        car_data["title"] = f"{car.make} {car.model}".strip()
        
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
        data = {
            "status": "Скрап",
            "scrap_price": scrap.scrap_price
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
def search_parts(q: Optional[str] = None):
    check_db()
    try:
        query = supabase.table("parts").select("*, warehouses(name), cars(make, model)").order("id", desc=True)
        if q:
            query = query.or_(f"title.ilike.%{q}%,make.ilike.%{q}%,model.ilike.%{q}%,oem_number.ilike.%{q}%")
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
        data = {
            "status": "Продадено",
            "sold_price": sell.sold_price
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


# === 5. AI АНАЛИЗ НА СНИМКИ (С РАБОТЕЩ GEMINI 1.5 FLASH МОДЕЛ) ===
@app.post("/ai-analyze")
async def ai_analyze(req: AiAnalyzeRequest):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: GEMINI_API_KEY is missing!", flush=True)
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY липсва в Render Environment.")

    try:
        # 1. Изтегляне на снимката от Cloudinary
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

        # 2. Подготовка на промпта
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

        # 3. Валиден URL с поддържан модел (gemini-1.5-flash)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        # 4. JSON Payload с правилните CamelCase ключове (inlineData и mimeType)
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
                print(f"Google REST Error ({api_res.status_code}): {api_res.text}", flush=True)
                raise HTTPException(
                    status_code=api_res.status_code, 
                    detail=f"Грешка от Google API ({api_res.status_code}): {api_res.text}"
                )

            res_data = api_res.json()

            # Извличане на отговора
            raw_text = ""
            try:
                raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                print(f"Invalid Google API response structure: {res_data}", flush=True)
                raise HTTPException(status_code=500, detail="Неочакван формат в отговора от Google API.")

            # Почистване от markdown тагове
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text.rsplit("\n", 1)[0]
                raw_text = raw_text.replace("json", "").strip()

            return {"result": json.loads(raw_text)}

    except json.JSONDecodeError:
        print(f"JSON Parsing Error. Raw text from AI was: {raw_text}", flush=True)
        raise HTTPException(status_code=500, detail="AI върна текст, който не може да бъде разпознат като JSON.")
    except Exception as e:
        print(f"Unhandled Exception in /ai-analyze: {str(e)}", flush=True)
        raise HTTPException(status_code=500, detail=f"Грешка AI Анализ: {str(e)}")


# === 6. ФИНАНСОВИ РЕЗУЛТАТИ ===
@app.get("/reports/financials")
def get_financials():
    check_db()
    cars = supabase.table("cars").select("purchase_price, scrap_price, status").execute().data or []
    parts = supabase.table("parts").select("price, sold_price, status").execute().data or []
    return {"cars": cars, "parts": parts}
