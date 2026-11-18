/* BookFlow AI mobile prototype. API key is held only in page memory. */
const $=id=>document.getElementById(id);
if(window.pdfjsLib) pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
let pdf=null, translated=[], docBlob=null, busy=false;
$("saveKey").onclick=()=>{$("keyState").textContent=$("apiKey").value.trim()?"کلید تا زمان بسته‌شدن صفحه در حافظه است.":"ابتدا کلید را وارد کن."};
$("pdfFile").onchange=async e=>{
 const f=e.target.files[0]; if(!f)return;
 try{const data=await f.arrayBuffer();pdf=await pdfjsLib.getDocument({data}).promise;
 $("pdfInfo").textContent=`فایل: ${f.name} | تعداد صفحات: ${pdf.numPages}`;
 $("start").disabled=false;
 }catch(err){$("pdfInfo").textContent="خواندن PDF ناموفق بود: "+err.message;pdf=null;$("start").disabled=true;}
};
function splitText(s,max=8500){let out=[],cur="";for(const p of s.split(/\n+/)){if((cur+p).length>max&&cur){out.push(cur);cur=p+"\n"}else cur+=p+"\n"}if(cur.trim())out.push(cur);return out}
async function callGemini(text){
 const key=$("apiKey").value.trim(); if(!key)throw Error("API Key را وارد کن.");
 const model=$("model").value;
 const prompt=`تو مترجم و ویراستار حرفه‌ای انگلیسی به فارسی هستی. متن زیر را با سبک «${$("style").value}» ترجمه کن. وفاداری کامل به معنا، تمام جزئیات، نام‌ها، اعداد، ارجاعات و ساختار استدلال الزامی است. چیزی را خلاصه یا حذف نکن و اطلاعاتی از خودت اضافه نکن. نثر فارسی طبیعی و معیار باشد. فقط ترجمه را برگردان.\n\nمتن:\n${text}`;
 const r=await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${encodeURIComponent(key)}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({contents:[{parts:[{text:prompt}]}],generationConfig:{temperature:0.2}})});
 const j=await r.json();if(!r.ok)throw Error(j.error?.message||`خطای API ${r.status}`);
 return j.candidates?.[0]?.content?.parts?.map(x=>x.text||"").join("")||"";
}
$("start").onclick=async()=>{
 if(busy||!pdf)return;busy=true;$("start").disabled=true;translated=[];
 try{
  const pageLimit=Number($("chunkPages").value), chunks=[];
  for(let p=1;p<=pdf.numPages;p+=pageLimit){
   let s="";
   for(let n=p;n<Math.min(p+pageLimit,pdf.numPages+1);n++){
    const page=await pdf.getPage(n), content=await page.getTextContent();
    s+=content.items.map(x=>x.str).join(" ")+"\n";
   }
   if(!s.trim())throw Error(`در صفحات ${p} تا ${Math.min(p+pageLimit-1,pdf.numPages)} متن قابل استخراج پیدا نشد. احتمالاً PDF اسکن‌شده است.`);
   chunks.push({start:p,text:s});
  }
  for(let i=0;i<chunks.length;i++){
   $("status").textContent=`در حال ترجمه بخش ${i+1} از ${chunks.length} (شروع از صفحه ${chunks[i].start})`;
   translated.push(await callGemini(chunks[i].text));
   $("bar").style.width=`${Math.round((i+1)/chunks.length*100)}%`;
  }
  const {Document,Packer,Paragraph,TextRun,AlignmentType}=docx;
  const paras=[];
  translated.join("\n\n").split(/\n+/).filter(x=>x.trim()).forEach(t=>paras.push(new Paragraph({bidi:true,alignment:AlignmentType.RIGHT,children:[new TextRun({text:t, rightToLeft:true})]})));
  const d=new Document({sections:[{properties:{},children:paras}]});
  docBlob=await Packer.toBlob(d);
  $("download").disabled=false;$("resultInfo").textContent=`ترجمه ${chunks.length} بخش آماده است. فایل Word قابل دریافت است.`;$("status").textContent="ترجمه تمام شد.";
 }catch(err){$("status").textContent="پردازش متوقف شد: "+err.message;$("resultInfo").textContent="بخش‌های تکمیل‌شده فقط تا زمانی که این صفحه باز است در حافظه‌اند."}
 finally{busy=false;$("start").disabled=!pdf}
};
$("download").onclick=()=>{if(!docBlob)return;const a=document.createElement("a");a.href=URL.createObjectURL(docBlob);a.download="BookFlow-Translation.docx";a.click();URL.revokeObjectURL(a.href)};
if("serviceWorker" in navigator && location.protocol.startsWith("http"))navigator.serviceWorker.register("./sw.js").catch(()=>{});
