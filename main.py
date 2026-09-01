from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client
import google.generativeai as genai
import cloudinary
import cloudinary.uploader
import os
import json


app = FastAPI()

# --- 1. КОНФИГУРАЦИЯ НА ВЪНШНИ УСЛУГИ ---

# Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Gemini AI
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# Cloudinary (За качване на снимки)
CLOUDINARY_URL = os.environ.get("CLOUDINARY_URL", "")
if CLOUDINARY_URL:
    cloudinary.config(cloudinary_url=CLOUDINARY_URL)


# --- 2. PUDANTIC МОДЕЛИ (ДАННИ ОТ HTML) ---

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

class CarUpdate(BaseModel):
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    engine: Optional[str] = None
    fuel_type: Optional[str] = None
    purchase_price: Optional[float] = None
    warehouse_id: Optional[int] = None
    notes: Optional[str] = None
    status: Optional[str] = None
    scrap_price: Optional[float] = None

class PartCreate(BaseModel):
    title: str
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    oem_number: Optional[str] = None
    price: float
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
    warehouse_id: Optional[int] = None
    car_id: Optional[int] = None
    notes: Optional[str] = None

class PartSell(BaseModel):
    sold_price: float

class ScrapCar(BaseModel):
    scrap_price: float

class AiAnalyzeRequest(BaseModel):
    image_url: str
    type: str  # 'car' или 'part'


# --- 3. СКЛАДОВЕ (WAREHOUSES) ---

@app.get("/warehouses")
async def get_warehouses():
    try:
        res = supabase.table("warehouses").select("*").execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/warehouses")
async def create_warehouse(data: WarehouseCreate):
    try:
        res = supabase.table("warehouses").insert(data.model_dump(exclude_none=True)).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/warehouses/{wh_id}")
async def update_warehouse(wh_id: int, data: WarehouseCreate):
    try:
        res = supabase.table("warehouses").update(data.model_dump(exclude_none=True)).eq("id", wh_id).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/warehouses/{wh_id}")
async def delete_warehouse(wh_id: int):
    try:
        supabase.table("warehouses").delete().eq("id", wh_id).execute()
        return {"message": "Складът е изтрит успешно"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 4. КОЛИ-ДОНОРИ (CARS) ---

@app.get("/cars/summary")
async def get_cars_summary():
    try:
        cars_res = supabase.table("cars").select("*, warehouses(name)").execute()
        cars = cars_res.data or []
        
        parts_res = supabase.table("parts").select("id, title, sold_price, status, car_id").execute()
        parts = parts_res.data or []

        for car in cars:
            car_parts = [p for p in parts if p.get("car_id") == car["id"]]
            car_sales = sum([p.get("sold_price") or 0 for p in car_parts if p.get("status") == "Продадено"])
            
            scrap_val = car.get("scrap_price") or 0
            total_sales = car_sales + scrap_val
            net_profit = total_sales - (car.get("purchase_price") or 0)
            
            car["total_sales"] = total_sales
            car["net_profit"] = net_profit
            car["parts"] = car_parts
            car["title"] = car.get("title") or f"{car.get('make', '')} {car.get('model', '')}".strip()

        return cars
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cars")
async def create_car(data: CarCreate):
    try:
        car_dict = data.model_dump(exclude_none=True)
        car_dict["title"] = f"{data.make} {data.model}".strip()
        car_dict["status"] = "Наличен"
        res = supabase.table("cars").insert(car_dict).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/cars/{car_id}")
async def update_car(car_id: int, data: CarUpdate):
    try:
        update_dict = data.model_dump(exclude_none=True)
        
        if "make" in update_dict or "model" in update_dict:
            current = supabase.table("cars").select("*").eq("id", car_id).single().execute().data
            make = update_dict.get("make", current.get("make"))
            model = update_dict.get("model", current.get("model"))
            update_dict["title"] = f"{make} {model}".strip()
            
        res = supabase.table("cars").update(update_dict).eq("id", car_id).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/cars/{car_id}/scrap")
async def scrap_car(car_id: int, data: ScrapCar):
    try:
        res = supabase.table("cars").update({
            "status": "Скрап",
            "scrap_price": data.scrap_price
        }).eq("id", car_id).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/cars/{car_id}")
async def delete_car(car_id: int):
    try:
        supabase.table("cars").delete().eq("id", car_id).execute()
        return {"message": "Колата е изтрита успешно"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 5. ЧАСТИ (PARTS) ---

@app.get("/parts/search")
async def search_parts():
    try:
        res = supabase.table("parts").select("*, warehouses(name), cars(make, model)").order("created_at", desc=True).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/parts")
async def create_part(data: PartCreate):
    try:
        part_dict = data.model_dump(exclude_none=True)
        part_dict["status"] = "Наличен"
        res = supabase.table("parts").insert(part_dict).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/parts/{part_id}")
async def update_part(part_id: int, data: PartUpdate):
    try:
        res = supabase.table("parts").update(data.model_dump(exclude_none=True)).eq("id", part_id).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/parts/{part_id}/sell")
async def sell_part(part_id: int, data: PartSell):
    try:
        res = supabase.table("parts").update({
            "status": "Продадено",
            "sold_price": data.sold_price
        }).eq("id", part_id).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/parts/{part_id}")
async def delete_part(part_id: int):
    try:
        supabase.table("parts").delete().eq("id", part_id).execute()
        return {"message": "Частта е изтрита успешно"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 6. ФИНАНСОВИ РЕЗУЛТАТИ (REPORTS) ---

@app.get("/reports/financials")
async def get_financials():
    try:
        cars = supabase.table("cars").select("*").execute().data or []
        parts = supabase.table("parts").select("*").execute().data or []
        return {"cars": cars, "parts": parts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- 7. МЕДИЯ & AI (CLOUDINARY & GEMINI) ---

@app.post("/upload-photos")
async def upload_photos(files: List[UploadFile] = File(...)):
    photo_urls = []
    try:
        for file in files:
            contents = await file.read()
            upload_result = cloudinary.uploader.upload(contents)
            photo_urls.append(upload_result.get("secure_url"))
        return {"photo_urls": photo_urls}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Грешка при качване на снимка: {str(e)}")

@app.post("/ai-analyze")
async def ai_analyze(req: AiAnalyzeRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Gemini API key липсва")

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if req.type == 'car':
            prompt = """
            Анализирай тази снимка на автомобил и върни JSON обект със следните ключове:
            - make (марка)
            - model (модел)
            - year (година като число или null)
            - engine (обем/двигател като текст или null)
            - fuel_type (само едно от следните: "Дизел", "Бензин", "Газ/Бензин", "Електрически", "Хибрид" или null)
            Върни САМО чист JSON без допълнителен текст или markdown.
            """
        else:
            prompt = """
            Анализирай тази снимка на авточаст и върни JSON обект със следните ключове:
            - title (название на частта на български)
            - make (марка автомобил ако е видимо)
            - model (модел автомобил ако е видимо)
            - year (година ако е видимо)
            - oem_number (OEM/сериен номер ако е видим на снимката)
            Върни САМО чист JSON без допълнителен текст или markdown.
            """

        import urllib.request
        with urllib.request.urlopen(req.image_url) as response:
            image_data = response.read()

        image_part = {
            "mime_type": "image/jpeg",
            "data": image_data
        }

        response = model.generate_content([prompt, image_part])
        cleaned_text = response.text.strip().replace("```json", "").replace("```", "")
        parsed_json = json.loads(cleaned_text)
        
        return parsed_json

    except Exception as e:
        print("AI Грешка:", str(e))
        return {}
