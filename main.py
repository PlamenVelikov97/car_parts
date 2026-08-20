import os
import json
from typing import Optional, List
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from supabase import create_client, Client
from openai import OpenAI

app = FastAPI()

# Разрешаваме CORS за достъп от браузъра
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Инициализация на Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ВНИМАНИЕ: Липсват SUPABASE_URL или SUPABASE_KEY в Environment Variables!")

supabase: Client = create_client(SUPABASE_URL or "", SUPABASE_KEY or "")

# 2. Инициализация на OpenAI
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


# --- PYDANTIC МОДЕЛИ ЗА ВЪВЕЖДАНЕ НА ДАННИ ---

class AIAnalyzeRequest(BaseModel):
    image_url: str
    type: str  # 'car' или 'part'

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
    warehouse_id: int
    notes: Optional[str] = None
    photo_urls: Optional[List[str]] = []

class PartCreate(BaseModel):
    title: str
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    oem_number: Optional[str] = None
    price: float
    status: Optional[str] = "Налично"
    warehouse_id: Optional[int] = None
    car_id: Optional[int] = None
    notes: Optional[str] = None
    photo_urls: Optional[List[str]] = []
    photo_url: Optional[str] = None

class SellPartRequest(BaseModel):
    sold_price: float


# --- ОСНОВЕН РУТ ЗА УЕБ СТРАНИЦАТА ---

@app.get("/")
async def read_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"message": "Auto Parts API is running!"}


# --- 1. AI АНАЛИЗ НА СНИМКИ (OPENAI VISION) ---

@app.post("/ai-analyze")
async def ai_analyze(data: AIAnalyzeRequest):
    if not openai_client:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY не е конфигуриран в Render!")

    if not data.image_url:
        raise HTTPException(status_code=400, detail="Няма предоставена снимка.")

    if data.type == 'car':
        prompt = """Анализирай тази снимка на автомобил. Върни САМО валиден JSON обект (без допълнителен маркдаун или текст) със следните полета:
        {
          "make": "Марка (напр. BMW, Audi, VW)",
          "model": "Модел (напр. 320, A4, Golf)",
          "year": Година като число (ако може да се определи от поколението, иначе null),
          "engine": "Обем/Двигател (ако личи надпис, иначе null)",
          "fuel_type": "Дизел/Бензин/Електро/null"
        }"""
    else:
        prompt = """Анализирай тази снимка на авточаст. Върни САМО валиден JSON обект (без допълнителен маркдаун или текст) със следните полета:
        {
          "title": "Точно наименование на частта на български (напр. Предна броня, Алтернатор, Скоростна кутия)",
          "make": "Марка на автомобила (ако има емблема/лого, иначе null)",
          "model": "Модел автомобил (ако личи, иначе null)",
          "year": Година като число (ако личи, иначе null),
          "oem_number": "OEM номер (ако се вижда ясно сериен номер, иначе null)"
        }"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data.image_url}}
                    ]
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=300
        )

        result_json = json.loads(response.choices[0].message.content)
        return result_json

    except Exception as e:
        print(f"Грешка при AI анализа: {e}")
        raise HTTPException(status_code=500, detail=f"Грешка при AI анализа: {str(e)}")


# --- 2. КАЧВАНЕ НА СНИМКИ В SUPABASE BUCKET ---

@app.post("/upload-photos")
async def upload_photos(files: List[UploadFile] = File(...)):
    uploaded_urls = []
    
    for file in files:
        try:
            file_bytes = await file.read()
            # Генерираме уникално име за файла
            file_ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
            file_name = f"part_{os.urandom(8).hex()}.{file_ext}"

            # Качваме в Supabase Storage (Bucket с име 'parts-photos')
            res = supabase.storage.from_("parts-photos").upload(
                file_name,
                file_bytes,
                file_options={"content-type": file.content_type or "image/jpeg"}
            )

            # Вземаме публичния URL адрес на качения файл
            public_url = supabase.storage.from_("parts-photos").get_public_url(file_name)
            uploaded_urls.append(public_url)
        except Exception as e:
            print(f"Грешка при качване на снимка {file.filename}: {e}")

    return {"photo_urls": uploaded_urls}


# --- 3. СКЛАДОВЕ (WAREHOUSES) ---

@app.get("/warehouses")
async def get_warehouses():
    res = supabase.table("warehouses").select("*").execute()
    return res.data

@app.post("/warehouses")
async def create_warehouse(data: WarehouseCreate):
    res = supabase.table("warehouses").insert(data.dict()).execute()
    return res.data

@app.put("/warehouses/{wh_id}")
async def update_warehouse(wh_id: int, data: WarehouseCreate):
    res = supabase.table("warehouses").update(data.dict()).eq("id", wh_id).execute()
    return res.data

@app.delete("/warehouses/{wh_id}")
async def delete_warehouse(wh_id: int):
    res = supabase.table("warehouses").delete().eq("id", wh_id).execute()
    return res.data


# --- 4. КОЛИ - ДОНОРИ (CARS) ---

@app.get("/cars")
async def get_cars():
    res = supabase.table("cars").select("*, warehouses(*)").execute()
    return res.data

@app.get("/cars/summary")
async def get_cars_summary():
    # Вземаме коли с финансови изчисления (продажби и печалба)
    cars_res = supabase.table("cars").select("*, warehouses(*)").execute()
    parts_res = supabase.table("parts").select("car_id, price, sold_price, status").execute()
    
    cars = cars_res.data or []
    parts = parts_res.data or []

    for car in cars:
        car_parts = [p for p in parts if p.get("car_id") == car["id"]]
        total_sales = sum((p.get("sold_price") or p.get("price") or 0) for p in car_parts if p.get("status") == "Продадено")
        
        car["title"] = f"{car.get('make', '')} {car.get('model', '')} ({car.get('year', '')})".strip()
        car["total_sales"] = total_sales
        car["net_profit"] = total_sales - (car.get("purchase_price") or 0)

    return cars

@app.post("/cars")
async def create_car(data: CarCreate):
    res = supabase.table("cars").insert(data.dict()).execute()
    return res.data

@app.put("/cars/{car_id}")
async def update_car(car_id: int, data: CarCreate):
    res = supabase.table("cars").update(data.dict()).eq("id", car_id).execute()
    return res.data

@app.delete("/cars/{car_id}")
async def delete_car(car_id: int):
    res = supabase.table("cars").delete().eq("id", car_id).execute()
    return res.data


# --- 5. ЧАСТИ (PARTS) ---

@app.get("/parts/search")
async def search_parts():
    res = supabase.table("parts").select("*, warehouses(*), cars(*)").order("id", desc=True).execute()
    return res.data

@app.post("/parts")
async def create_part(data: PartCreate):
    res = supabase.table("parts").insert(data.dict()).execute()
    return res.data

@app.put("/parts/{part_id}")
async def update_part(part_id: int, data: PartCreate):
    res = supabase.table("parts").update(data.dict()).eq("id", part_id).execute()
    return res.data

@app.put("/parts/{part_id}/sell")
async def sell_part(part_id: int, data: SellPartRequest):
    update_data = {
        "status": "Продадено",
        "sold_price": data.sold_price,
        "sold_date": "now()"
    }
    res = supabase.table("parts").update(update_data).eq("id", part_id).execute()
    return res.data

@app.delete("/parts/{part_id}")
async def delete_part(part_id: int):
    res = supabase.table("parts").delete().eq("id", part_id).execute()
    return res.data
