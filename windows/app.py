import io, re, hashlib, sqlite3
from pathlib import Path
from datetime import datetime

import streamlit as st
import fitz
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from google import genai
from google.genai import types

ROOT = Path(__file__).parent
DATA = ROOT / "bookflow_data"
DATA.mkdir(exist_ok=True)
DB = DATA / "bookflow.sqlite3"
st.set_page_config(page_title="BookFlow AI", page_icon="📚", layout="wide")

def connect():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY, filename TEXT, title TEXT, style TEXT,
            created_at TEXT, total_chunks INTEGER, total_words INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS chunks (
            job_id TEXT, chunk_no INTEGER, source TEXT, translated TEXT,
            status TEXT DEFAULT 'pending', error TEXT, updated_at TEXT,
            PRIMARY KEY(job_id, chunk_no))""")
init_db()

def split_chunks(text, limit):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result, current, count = [], [], 0
    for para in paras:
        words = para.split()
        if len(words) > limit:
            if current:
                result.append("\n\n".join(current)); current=[]; count=0
            result.extend(" ".join(words[i:i+limit]) for i in range(0, len(words), limit))
        else:
            if current and count + len(words) > limit:
                result.append("\n\n".join(current)); current=[]; count=0
            current.append(para); count += len(words)
    if current: result.append("\n\n".join(current))
    return result

def extract_pdf(data):
    doc = fitz.open(stream=data, filetype="pdf")
    pages = [(i, p.get_text("text", sort=True).strip()) for i,p in enumerate(doc,1)]
    text = "\n\n".join(f"[صفحه {i}]\n{t}" for i,t in pages if t)
    return text, len(doc), len(text.split())

def make_job(filename, data, title, style, limit):
    text, pages, words = extract_pdf(data)
    if not text.strip():
        raise ValueError("متنی از PDF استخراج نشد؛ احتمالاً فایل اسکن‌شده است و OCR در این نسخه وجود ندارد.")
    parts = split_chunks(text, limit)
    jid = hashlib.sha256(data).hexdigest()[:16]
    with connect() as c:
        if not c.execute("SELECT 1 FROM jobs WHERE job_id=?", (jid,)).fetchone():
            c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                (jid, filename, title or Path(filename).stem, style,
                 datetime.now().isoformat(timespec="seconds"), len(parts), words))
            for n, part in enumerate(parts, 1):
                c.execute("INSERT INTO chunks(job_id,chunk_no,source,status) VALUES(?,?,?,'pending')",
                          (jid,n,part))
    return jid,pages,words,len(parts)

def get_job(jid):
    with connect() as c:
        job=c.execute("SELECT * FROM jobs WHERE job_id=?",(jid,)).fetchone()
        chunks=c.execute("SELECT * FROM chunks WHERE job_id=? ORDER BY chunk_no",(jid,)).fetchall()
    return job,chunks

def translate(key, model, source, style, title):
    prompt=f"""تو مترجم حرفه‌ای انگلیسی به فارسی و ویراستار کتاب هستی.
عنوان کتاب: {title}
سبک ترجمه: {style}
متن را کامل، دقیق و وفادار ترجمه کن. چیزی را حذف یا خلاصه نکن و چیزی از خودت نیفزا.
نام‌ها، اصطلاحات تخصصی، اعداد، تاریخ‌ها، نقل‌قول‌ها و ارجاعات را حفظ کن.
نثر فارسی طبیعی و معیار باشد. فقط متن ترجمه‌شده را برگردان.

متن:
---BEGIN SOURCE---
{source}
---END SOURCE---"""
    client=genai.Client(api_key=key)
    response=client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(temperature=0.25,max_output_tokens=8192))
    result=(response.text or "").strip()
    if not result: raise RuntimeError("پاسخ متنی از مدل دریافت نشد.")
    return result

def save_chunk(jid,n,translated=None,status="done",error=None):
    with connect() as c:
        c.execute("UPDATE chunks SET translated=?,status=?,error=?,updated_at=? WHERE job_id=? AND chunk_no=?",
                  (translated,status,error,datetime.now().isoformat(timespec="seconds"),jid,n))

def make_docx(job,chunks,include_source=False):
    doc=Document(); sec=doc.sections[0]
    sec.top_margin=Cm(2.2); sec.bottom_margin=Cm(2.2)
    sec.left_margin=Cm(2.3); sec.right_margin=Cm(2.3)
    doc.styles["Normal"].font.name="B Nazanin"; doc.styles["Normal"].font.size=Pt(13)
    h=doc.add_heading(job["title"],0); h.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p=doc.add_paragraph("ترجمه با BookFlow AI"); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    doc.add_page_break()
    for ch in chunks:
        if ch["status"]!="done" or not ch["translated"]: continue
        if include_source:
            h=doc.add_heading(f"بخش {ch['chunk_no']} — متن اصلی",2); h.alignment=WD_ALIGN_PARAGRAPH.RIGHT
            for line in ch["source"].split("\n\n"):
                p=doc.add_paragraph(line); p.alignment=WD_ALIGN_PARAGRAPH.LEFT
            doc.add_heading(f"بخش {ch['chunk_no']} — ترجمه فارسی",2)
        for line in ch["translated"].split("\n"):
            if line.strip():
                p=doc.add_paragraph(line.strip()); p.alignment=WD_ALIGN_PARAGRAPH.RIGHT
                p.paragraph_format.line_spacing=1.25; p.paragraph_format.space_after=Pt(6)
    b=io.BytesIO(); doc.save(b); return b.getvalue()

st.title("📚 BookFlow AI")
st.caption("میزکار محلی ترجمه کتاب انگلیسی به فارسی — نسخه اولیه ویندوز")
with st.sidebar:
    st.header("تنظیمات موتور هوش مصنوعی")
    api_key=st.text_input("Gemini API Key",type="password",
        help="کلید را در Google AI Studio بسازید. این برنامه آن را در پایگاه داده ذخیره نمی‌کند.")
    model=st.text_input("نام مدل",value="gemini-2.5-flash")
    st.caption("دسترسی رایگان و سهمیه مدل‌ها ممکن است تغییر کند؛ سقف مصرف را در AI Studio بررسی کنید.")
    st.divider()
    st.caption("متن کتاب برای ترجمه به Gemini ارسال می‌شود. فایل‌ها و خروجی‌ها محلی ذخیره می‌شوند.")

new_tab,jobs_tab,help_tab=st.tabs(["➕ پروژه جدید","📂 پروژه‌ها و ادامه کار","راهنما"])
with new_tab:
    st.subheader("۱. بارگذاری PDF متنی")
    uploaded=st.file_uploader("فایل PDF انگلیسی را انتخاب کن",type=["pdf"])
    c1,c2=st.columns(2)
    with c1:
        title=st.text_input("عنوان کتاب (اختیاری)")
        style=st.selectbox("سبک ترجمه",["رسمی، روان و مناسب انتشار کتاب","علمی و دانشگاهی",
            "تحلیلی و تخصصی علوم سیاسی و مطالعات منطقه‌ای","روان و عمومی"])
    with c2:
        limit=st.select_slider("حداکثر کلمات هر بخش",options=[1000,1500,2000,2500,3000,3500,4000],value=2000)
        st.caption("برای شروع ۲۰۰۰ کلمه پیشنهاد می‌شود.")
    if uploaded and st.button("استخراج متن و ساخت پروژه",type="primary"):
        try:
            with st.spinner("در حال استخراج متن..."):
                jid,pages,words,count=make_job(uploaded.name,uploaded.getvalue(),title,style,limit)
            st.success(f"پروژه آماده شد: {pages} صفحه، حدود {words:,} کلمه، {count} بخش.")
            st.info("برای ترجمه به زبانه پروژه‌ها و ادامه کار برو.")
        except Exception as e: st.error(str(e))

with jobs_tab:
    st.subheader("۲. انتخاب پروژه و ترجمه")
    with connect() as c: jobs=c.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    if not jobs: st.info("هنوز پروژه‌ای نساخته‌ای.")
    else:
        opts={f"{j['title']} | {j['created_at'][:16]} | {j['job_id']}":j["job_id"] for j in jobs}
        jid=opts[st.selectbox("پروژه",list(opts.keys()))]
        job,chunks=get_job(jid)
        done=sum(x["status"]=="done" for x in chunks)
        failed=sum(x["status"]=="error" for x in chunks)
        pending=len(chunks)-done-failed
        a,b,c,d=st.columns(4)
        a.metric("کل بخش‌ها",len(chunks)); b.metric("تکمیل‌شده",done)
        c.metric("باقی‌مانده",pending); d.metric("خطادار",failed)
        st.progress(done/max(len(chunks),1))
        st.caption(f"حجم متن: حدود {job['total_words']:,} کلمه")
        batch=st.number_input("حداکثر بخش در این نوبت",min_value=1,max_value=50,value=3)
        if st.button("▶ شروع / ادامه ترجمه",type="primary",disabled=not bool(api_key)):
            todo=[x for x in chunks if x["status"]!="done"][:int(batch)]
            bar=st.progress(0); status=st.empty()
            for i,ch in enumerate(todo,1):
                try:
                    status.write(f"در حال ترجمه بخش {ch['chunk_no']} از {len(chunks)}...")
                    result=translate(api_key,model,ch["source"],job["style"],job["title"])
                    save_chunk(jid,ch["chunk_no"],result,"done",None)
                except Exception as e:
                    msg=str(e); save_chunk(jid,ch["chunk_no"],None,"error",msg[:1000])
                    status.error("خطا: "+msg)
                    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                        st.warning("به محدودیت سهمیه یا نرخ درخواست رسیده‌ای. بعداً ادامه بده."); break
                bar.progress(i/max(len(todo),1))
            st.success("این نوبت پایان یافت؛ وضعیت به‌روزرسانی می‌شود.")
            st.rerun()
        job,chunks=get_job(jid)
        with st.expander("وضعیت بخش‌ها"):
            for ch in chunks:
                mark="✅" if ch["status"]=="done" else ("⚠️" if ch["status"]=="error" else "⏳")
                st.write(f"{mark} بخش {ch['chunk_no']} — {len(ch['source'].split()):,} کلمه")
                if ch["status"]=="error": st.caption(ch["error"] or "")
        if done:
            st.subheader("۳. دریافت خروجی Word")
            include=st.checkbox("متن انگلیسی هر بخش هم در فایل بیاید",value=False)
            safe=re.sub(r"[^\w\-]+","_",job["title"]).strip("_") or "book"
            st.download_button("⬇ دریافت فایل Word",data=make_docx(job,chunks,include),
                file_name=f"{safe}_fa_BookFlow.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            if pending or failed: st.caption("خروجی فعلی فقط بخش‌های تکمیل‌شده را شامل می‌شود.")
        if failed and st.button("بازنشانی بخش‌های خطادار"):
            with connect() as c:
                c.execute("UPDATE chunks SET status='pending',error=NULL WHERE job_id=? AND status='error'",(jid,))
            st.rerun()

with help_tab:
    st.subheader("راهنمای سریع")
    st.markdown("""
1. Python 3.11 یا 3.12 نسخه ۶۴ بیتی را نصب کن و گزینه Add Python to PATH را فعال کن.
2. فایل install.bat را اجرا کن.
3. از Google AI Studio کلید API بگیر.
4. فایل start.bat را اجرا کن و کلید را در نوار کناری وارد کن.
5. PDF متنی را بارگذاری کن، پروژه را بساز و ترجمه را در نوبت‌های کوچک انجام بده.
6. پس از تکمیل، فایل Word را دریافت کن.

**محدودیت‌ها:** PDF اسکن‌شده، OCR، حفظ جدول و تصویر و صفحه‌آرایی اصلی در این نسخه پشتیبانی نمی‌شود. سهمیه رایگان Gemini تضمین‌شده نیست. متن ارسالی به سرویس گوگل منتقل می‌شود و باید پیش از انتشار انسانی بازبینی شود.
""")
    st.subheader("محل ذخیره اطلاعات")
    st.code(str(DATA),language="text")
    st.caption("برای پشتیبان‌گیری، پوشه bookflow_data را کپی کن.")
