from __future__ import annotations
import asyncio, re, socket, sqlite3, uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any
import fitz, httpx
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE=Path(__file__).resolve().parent
DATA=BASE/"data"; UPLOADS=DATA/"uploads"; OUTPUTS=DATA/"outputs"; STATIC=BASE/"static"; DB=DATA/"bookflow.sqlite3"
for folder in (DATA,UPLOADS,OUTPUTS,STATIC): folder.mkdir(parents=True,exist_ok=True)
CONFIG: dict[str,dict[str,str]]={}
PAUSE_FLAGS: dict[str,asyncio.Event]={}
TASKS: dict[str,asyncio.Task]={}
CHAPTER_RE=re.compile(r"^\s*(?:chapter|part|section)\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b.*$",re.I)

@contextmanager
def connect():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,filename TEXT NOT NULL,status TEXT NOT NULL,total INTEGER NOT NULL,completed INTEGER NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,error TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,seq INTEGER NOT NULL,chapter TEXT NOT NULL,source TEXT NOT NULL,translation TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'pending',UNIQUE(job_id,seq));
        """)
        con.execute("UPDATE jobs SET status='paused' WHERE status='running'")
        con.execute("UPDATE chunks SET status='pending' WHERE status='working'")

@asynccontextmanager
async def lifespan(app):
    init_db(); yield

app=FastAPI(title="BookFlow AI 2",version="2.0.0",lifespan=lifespan)
app.mount("/static",StaticFiles(directory=STATIC),name="static")

@app.get("/")
async def home(): return FileResponse(STATIC/"index.html")

def local_ip():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(("192.0.2.1",80)); ip=s.getsockname()[0]; s.close(); return ip
    except OSError: return "آدرس IP را از تنظیمات Wi-Fi ویندوز پیدا کن"

def pdf_to_text(path):
    doc=fitz.open(path); pages=[]
    for page in doc:
        blocks=page.get_text("blocks",sort=True)
        text="\n".join(str(b[4]).strip() for b in blocks if len(b)>4 and str(b[4]).strip())
        if text: pages.append(text)
    doc.close(); return "\n\n".join(pages)

def split_book(text,limit=6000):
    lines=[x.strip() for x in text.replace("\r","").split("\n")]
    heads=[(i,x) for i,x in enumerate(lines) if CHAPTER_RE.match(x)]
    if not heads: raw=[("متن کتاب","\n".join(lines))]
    else:
        raw=[]
        if heads[0][0]>0: raw.append(("مقدمه و مطالب آغازین","\n".join(lines[:heads[0][0]])))
        for n,(start,title) in enumerate(heads):
            end=heads[n+1][0] if n+1<len(heads) else len(lines)
            raw.append((title,"\n".join(lines[start:end])))
    result=[]
    for title,body in raw:
        paragraphs=[p.strip() for p in re.split(r"\n\s*\n",body) if p.strip()]
        units=[]
        for p in paragraphs:
            while len(p)>limit:
                cut=max(p.rfind(". ",0,limit),p.rfind("? ",0,limit),p.rfind("! ",0,limit),p.rfind(" ",0,limit))
                if cut<limit//2: cut=limit
                units.append(p[:cut+1].strip()); p=p[cut+1:].strip()
            if p: units.append(p)
        current=""
        for unit in units:
            if current and len(current)+len(unit)+2>limit: result.append((title,current)); current=unit
            else: current=(current+"\n\n"+unit).strip()
        if current: result.append((title,current))
    return result

class StartRequest(BaseModel):
    provider:str=Field(pattern="^(gemini|openai|xai|openrouter)$")
    model:str=Field(min_length=1,max_length=160)
    api_key:str=Field(min_length=8,max_length=500)
    style:str="ترجمه دانشگاهی دقیق و روان"
    glossary:str=""

def get_job(job_id):
    with connect() as con:
        row=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone()
        if not row: raise HTTPException(404,"کتاب پیدا نشد.")
        chunks=con.execute("SELECT seq,chapter,status FROM chunks WHERE job_id=? ORDER BY seq",(job_id,)).fetchall()
    return {**dict(row),"chunks":[dict(c) for c in chunks],"progress":round(100*row["completed"]/max(1,row["total"]))}

@app.get("/api/network")
async def network(): return {"local_url":"http://"+local_ip()+":8000","note":"گوشی و لپ‌تاپ باید به یک Wi-Fi وصل باشند."}

@app.post("/api/upload")
async def upload_pdf(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"): raise HTTPException(400,"فقط فایل PDF پذیرفته می‌شود.")
    job_id=uuid.uuid4().hex[:12]; path=UPLOADS/(job_id+".pdf"); raw=await file.read()
    if len(raw)>100*1024*1024: raise HTTPException(413,"حجم فایل بیشتر از ۱۰۰ مگابایت است.")
    path.write_bytes(raw)
    try: text=pdf_to_text(path)
    except Exception as exc:
        path.unlink(missing_ok=True); raise HTTPException(400,"خواندن PDF ناموفق بود: "+str(exc))
    if len(text.strip())<100:
        path.unlink(missing_ok=True); raise HTTPException(422,"متن قابل استخراج پیدا نشد؛ احتمالاً PDF اسکن‌شده است. OCR هنوز فعال نیست.")
    chunks=split_book(text)
    if not chunks: raise HTTPException(422,"متنی برای ترجمه پیدا نشد.")
    with connect() as con:
        con.execute("INSERT INTO jobs(id,filename,status,total) VALUES(?,?,?,?)",(job_id,file.filename,"ready",len(chunks)))
        con.executemany("INSERT INTO chunks(job_id,seq,chapter,source) VALUES(?,?,?,?)",[(job_id,i+1,t,b) for i,(t,b) in enumerate(chunks)])
    return {"id":job_id,"filename":file.filename,"total_chunks":len(chunks),"chapters":list(dict.fromkeys(t for t,_ in chunks))}

@app.get("/api/jobs")
async def jobs():
    with connect() as con: rows=con.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/jobs/{job_id}")
async def job_status(job_id:str): return get_job(job_id)

def make_prompt(source,chapter,seq,style,glossary):
    glossary_text="\nواژه‌نامه الزامی:\n"+glossary+"\n" if glossary.strip() else ""
    return ("متن زیر بخشی از یک کتاب انگلیسی است. آن را به فارسی معیار و دقیق ترجمه کن. هیچ جمله، مثال، عدد، ارجاع یا پاراگرافی را حذف یا خلاصه نکن. چیزی از خودت اضافه نکن. عنوان‌ها، فهرست‌ها و شکست پاراگراف‌ها را حفظ کن. نام‌ها و اصطلاحات را در سراسر کتاب یکسان ترجمه کن. فقط متن ترجمه‌شده را برگردان.\nسبک: "+style+"\nفصل: "+chapter+" | بخش: "+str(seq)+glossary_text+"\nمتن مبدأ:\n"+source)

async def call_provider(cfg,prompt):
    provider,key,model=cfg["provider"],cfg["api_key"],cfg["model"]
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0,connect=30.0)) as client:
        if provider=="gemini":
            url="https://generativelanguage.googleapis.com/v1beta/models/"+model+":generateContent"
            r=await client.post(url,params={"key":key},json={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.2}})
            data=r.json()
            if r.is_error: raise RuntimeError(data.get("error",{}).get("message","خطای Gemini "+str(r.status_code)))
            answer="\n".join(p.get("text","") for p in data.get("candidates",[{}])[0].get("content",{}).get("parts",[])).strip()
        else:
            urls={"openai":"https://api.openai.com/v1/chat/completions","xai":"https://api.x.ai/v1/chat/completions","openrouter":"https://openrouter.ai/api/v1/chat/completions"}
            headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}
            if provider=="openrouter": headers["X-Title"]="BookFlow AI"
            r=await client.post(urls[provider],headers=headers,json={"model":model,"messages":[{"role":"system","content":"You are a careful professional English-to-Persian book translator."},{"role":"user","content":prompt}],"temperature":0.2})
            data=r.json()
            if r.is_error: raise RuntimeError(data.get("error",{}).get("message","خطای سرویس "+str(r.status_code)))
            answer=data.get("choices",[{}])[0].get("message",{}).get("content","")
            if isinstance(answer,list): answer="\n".join(x.get("text","") for x in answer if isinstance(x,dict))
            answer=str(answer).strip()
    if not answer: raise RuntimeError("پاسخ خالی از مدل دریافت شد.")
    return answer

async def translation_worker(job_id):
    cfg=CONFIG.get(job_id)
    if not cfg:
        with connect() as con: con.execute("UPDATE jobs SET status='paused',error=? WHERE id=?",("برای ادامه، تنظیمات سرویس را دوباره وارد کن.",job_id))
        return
    try:
        while True:
            await PAUSE_FLAGS.setdefault(job_id,asyncio.Event()).wait()
            with connect() as con:
                row=con.execute("SELECT * FROM chunks WHERE job_id=? AND status!='done' ORDER BY seq LIMIT 1",(job_id,)).fetchone()
            if not row:
                with connect() as con: con.execute("UPDATE jobs SET status='completed',error='' WHERE id=?",(job_id,))
                return
            with connect() as con: con.execute("UPDATE chunks SET status='working' WHERE id=?",(row["id"],))
            try: translated=await call_provider(cfg,make_prompt(row["source"],row["chapter"],row["seq"],cfg["style"],cfg["glossary"]))
            except Exception as exc:
                with connect() as con:
                    con.execute("UPDATE chunks SET status='pending' WHERE id=?",(row["id"],))
                    con.execute("UPDATE jobs SET status='paused',error=? WHERE id=?",(str(exc)[:1000],job_id))
                return
            with connect() as con:
                con.execute("UPDATE chunks SET translation=?,status='done' WHERE id=?",(translated,row["id"]))
                done=con.execute("SELECT COUNT(*) FROM chunks WHERE job_id=? AND status='done'",(job_id,)).fetchone()[0]
                con.execute("UPDATE jobs SET completed=?,status='running',error='' WHERE id=?",(done,job_id))
            if not PAUSE_FLAGS[job_id].is_set():
                with connect() as con: con.execute("UPDATE jobs SET status='paused' WHERE id=?",(job_id,))
                return
    except asyncio.CancelledError:
        with connect() as con: con.execute("UPDATE jobs SET status='paused' WHERE id=?",(job_id,))
        raise

@app.post("/api/jobs/{job_id}/start")
async def start_job(job_id:str,request:StartRequest):
    job=get_job(job_id)
    if job["status"]=="completed": raise HTTPException(409,"این کتاب قبلاً ترجمه شده است.")
    CONFIG[job_id]=request.model_dump()
    with connect() as con: con.execute("UPDATE jobs SET status='running',error='' WHERE id=?",(job_id,))
    if job_id in TASKS and not TASKS[job_id].done():
        PAUSE_FLAGS.setdefault(job_id,asyncio.Event()).set()
    else:
        PAUSE_FLAGS[job_id]=asyncio.Event()
        PAUSE_FLAGS[job_id].set()
        TASKS[job_id]=asyncio.create_task(translation_worker(job_id))
    return {"ok":True,"message":"ترجمه شروع شد."}

@app.post("/api/jobs/{job_id}/pause")
async def pause_job(job_id:str):
    get_job(job_id)
    if job_id in PAUSE_FLAGS: PAUSE_FLAGS[job_id].clear()
    with connect() as con: con.execute("UPDATE jobs SET status='paused' WHERE id=? AND status='running'",(job_id,))
    return {"ok":True}

def rtl_paragraph(p):
    p.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))

def rtl_run(run):
    rp=run._element.get_or_add_rPr(); rp.append(OxmlElement("w:rtl"))
    run.font.name="B Nazanin"; rp.rFonts.set(qn("w:eastAsia"),"B Nazanin")

@app.get("/api/jobs/{job_id}/download")
async def download_docx(job_id:str):
    job=get_job(job_id)
    if job["status"]!="completed": raise HTTPException(409,"ترجمه هنوز کامل نشده است.")
    with connect() as con: rows=con.execute("SELECT chapter,translation FROM chunks WHERE job_id=? ORDER BY seq",(job_id,)).fetchall()
    doc=Document()
    for row in rows:
        h=doc.add_paragraph(); rtl_paragraph(h); r=h.add_run(row["chapter"]); r.bold=True; rtl_run(r)
        for text in re.split(r"\n\s*\n",row["translation"]):
            if text.strip():
                p=doc.add_paragraph(); rtl_paragraph(p); rr=p.add_run(text.strip()); rtl_run(rr)
    output=OUTPUTS/(job_id+"-fa.docx"); doc.save(output)
    return FileResponse(output,filename="BookFlow-"+Path(job["filename"]).stem+"-FA.docx",media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

@app.get("/api/health")
async def health(): return {"ok":True,"version":"2.0.0"}

if __name__=="__main__":
    import uvicorn
    print("\nBookFlow AI 2")
    print("Laptop: http://127.0.0.1:8000")
    print("Phone (same Wi-Fi): http://"+local_ip()+":8000\n")
    uvicorn.run(app,host="0.0.0.0",port=8000)
