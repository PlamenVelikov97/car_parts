import os
import json
import base64
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader
import google.generativeai as genai

# === ИНИЦИАЛИЗАЦИЯ НА FASTAPI И JINJA2 ===
app = FastAPI(title="Автоморга Мениджър")
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# === НАСТРОЙКИ НА ВЪНШНИ УСЛУГИ (ENV VARIABLES) ===
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Свързване с Supabase
supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Свързване с Cloudinary
if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET
    )

# Свързване с Gemini AI
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


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
    purchase_price: float
    warehouse_id: Optional[int] = None
    notes: Optional[str] = None
    photo_urls: Optional[List[str]] = []

class CarScrap(BaseModel):
    scrap_price: float

class PartCreate(BaseModel):
    title: str
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    oem_number: Optional[str] = None
    price: float
    car_id: Optional[int] = None
    warehouse_id: Optional[int] = None
    notes: Optional[str] = None
    photo_urls: Optional[List[str]] = []

class PartSell(BaseModel):
    sold_price: float

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
    # Коригирано за съвместимост с най-новите версии на Starlette и Jinja2
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
    res = supabase.table("warehouses").insert(wh.dict()).execute()
    return res.data

@app.put("/warehouses/{wh_id}")
def update_warehouse(wh_id: int, wh: WarehouseCreate):
    check_db()
    res = supabase.table("warehouses").update(wh.dict()).eq("id", wh_id).execute()
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
    cars_res = supabase.table("cars").select("*, warehouses(name)").order("id", desc=True).execute()
    cars = cars_res.data or []

    parts_res = supabase.table("parts").select("id, car_id, title, status, price, sold_price").execute()
    parts = parts_res.data or []

    result = []
    for car in cars:
        car_parts = [p for p in parts if p.get("car_id") == car["id"]]
        sold_parts_sum = sum((p.get("sold_price") or 0.0) for p in car_parts if p.get("status") == "Продадено")
        scrap_price = car.get("scrap_price") or 0.0
        
        total_sales = sold_parts_sum + scrap_price
        purchase = car.get("purchase_price") or 0.0
        net_profit = total_sales - purchase

        car_data = dict(car)
        car_data["parts"] = car_parts
        car_data["parts_count"] = len(car_parts)
        car_data["total_sales"] = total_sales
        car_data["net_profit"] = net_profit
        car_data["title"] = f"{car.get('make', '')} {car.get('model', '')}".strip()
        result.append(car_data)

    return result

@app.post("/cars")
def create_car(car: CarCreate):
    check_db()
    car_data = car.dict()
    car_data["status"] = "Наличен"
    res = supabase.table("cars").insert(car_data).execute()
    return res.data

@app.put("/cars/{car_id}")
def update_car(car_id: int, car: CarCreate):
    check_db()
    res = supabase.table("cars").update(car.dict()).eq("id", car_id).execute()
    return res.data

@app.put("/cars/{car_id}/scrap")
def scrap_car(car_id: int, scrap: CarScrap):
    check_db()
    data = {
        "status": "Скрап",
        "scrap_price": scrap.scrap_price
    }
    res = supabase.table("cars").update(data).eq("id", car_id).execute()
    return res.data

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
    query = supabase.table("parts").select("*, warehouses(name), cars(make, model)").order("id", desc=True)
    if q:
        query = query.or_(f"title.ilike.%{q}%,make.ilike.%{q}%,model.ilike.%{q}%,oem_number.ilike.%{q}%")
    res = query.execute()
    return res.data

@app.post("/parts")
def create_part(part: PartCreate):
    check_db()
    part_data = part.dict()
    part_data["status"] = "Наличен"
    res = supabase.table("parts").insert(part_data).execute()
    return res.data

@app.put("/parts/{part_id}")
def update_part(part_id: int, part: PartCreate):
    check_db()
    res = supabase.table("parts").update(part.dict()).eq("id", part_id).execute()
    return res.data

@app.put("/parts/{part_id}/sell")
def sell_part(part_id: int, sell: PartSell):
    check_db()
    data = {
        "status": "Продадено",
        "sold_price": sell.sold_price
    }
    res = supabase.table("parts").update(data).eq("id", part_id).execute()
    return res.data

@app.delete("/parts/{part_id}")
def delete_part(part_id: int):
    check_db()
    res = supabase.table("parts").delete().eq("id", part_id).execute()
    return {"message": "Part deleted"}


# === 4. КАЧВАНЕ НА СНИМКИ (CLOUDINARY) ===
@app.post("/upload-photos")
async def upload_photos(files: List[UploadFile] = File(...)):
    if not CLOUDINARY_CLOUD_NAME:
        raise HTTPException(status_code=500, detail="Cloudinary не е конфигуриран на сървъра.")

    uploaded_urls = []
    for file in files:
        try:
            content = await file.read()
            res = cloudinary.uploader.upload(content)
            if "secure_url" in res:
                uploaded_urls.append(res["secure_url"])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Грешка при качване в Cloudinary: {str(e)}")

    return {"photo_urls": uploaded_urls}


# === 5. AI АНАЛИЗ НА СНИМКИ (GEMINI 2.5 FLASH) ===
@app.post("/ai-analyze")
async def ai_analyze(req: AiAnalyzeRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API ключът не е конфигуриран.")

    try:
        import requests
        img_res = requests.get(req.photo_url)
        if img_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Снимката не може да бъде изтеглена от Cloudinary.")

        image_data = img_res.content
        mime_type = img_res.headers.get("Content-Type", "image/jpeg")

        model = genai.GenerativeModel("gemini-2.5-flash")

        if req.type == "car":
            prompt = """
            Анализирай това изображение на автомобил и върни САМО валиден JSON обект без markdown обвивки.
            JSON структура:
            {
                "make": "Марка (напр. Audi, BMW)",
                "model": "Модел (напр. A4, X5)",
                "year": Година (число или null),
                "engine": "Двигател (напр. 2.0 TDI)",
                "fuel_type": "Тип гориво (Дизел, Бензин, Газ/Бензин, Електрически, Хибрид)"
            }
            """
        else:
            prompt = """
            Анализирай това изображение на авточаст и върни САМО валиден JSON обект без markdown обвивки.
            JSON структура:
            {
                "title": "Име на частта (напр. Предна броня, Алтернатор)",
                "make": "Марка автомобил (ако се вижда)",
                "model": "Модел (ако се вижда)",
                "year": Година (число или null),
                "oem_number": "OEM или сериен номер (ако се вижда)"
            }
            """

        response = model.generate_content([
            {"mime_type": mime_type, "data": image_data},
            prompt
        ])

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        parsed_json = json.loads(text)
        return {"result": parsed_json}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Грешка AI Анализ: {str(e)}")


# === 6. ФИНАНСОВИ РЕЗУЛТАТИ ===
@app.get("/reports/financials")
def get_financials():
    check_db()
    cars = supabase.table("cars").select("purchase_price, scrap_price, status").execute().data or []
    parts = supabase.table("parts").select("price, sold_price, status").execute().data or []
    return {"cars": cars, "parts": parts}
