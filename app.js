/* BookFlow AI multi-provider mobile prototype. API key stays in page memory only. */
const $=id=>document.getElementById(id);
if(window.pdfjsLib) pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
let pdf=null, translated=[], docBlob=null, busy=false;

const providerHints={
 gemini:"Gemini از Interactions API استفاده می‌کند. شناسه مدل را از فهرست مدل‌های Google AI Studio بردار.",
 openai:"OpenAI از Responses API استفاده می‌کند. شناسه مدل باید در حساب API تو فعال باشد.",
 xai:"Grok از Responses API رسمی xAI استفاده می‌کند. شناسه مدل را از پنل xAI بردار.",
 openrouter:"OpenRouter از Chat Completions API استفاده می‌کند. شناسه مدل معمولاً به شکل provider/model است؛ مثل نام‌هایی که در فهرست مدل‌های OpenRouter می‌بینی."
};
const modelExamples={
 gemini:"مثلاً gemini-3.8-flash",
 openai:"شناسه مدل فعال در حساب OpenAI",
 xai:"شناسه مدل فعال در xAI، مثلاً grok-4.7",
 openrouter:"شناسه کامل مدل، مثلاً openai/model-name"
};
function updateProviderHelp(){
 const p=$("provider").value;
 $("providerHelp").textContent=providerHints[p];
 $("model").placeholder=modelExamples[p];
}
$("provider").addEventListener("change",updateProviderHelp);
updateProviderHelp();

$("saveKey").onclick=()=>{
 const key=$("apiKey").value.trim(), model=$("model").value.trim();
 $("keyState").textContent=!key?"ابتدا کلید API را وارد کن.":!model?"شناسه مدل را وارد کن.":"تنظیمات وارد شده‌اند؛ برای آزمودن اتصال، ترجمه را شروع کن.";
};
$("pdfFile").onchange=async e=>{
 const f=e.target.files[0]; if(!f)return;
 try{
  const data=await f.arrayBuffer();pdf=await pdfjsLib.getDocument({data}).promise;
  $("pdfInfo").textContent=`فایل: ${f.name} | تعداد صفحات: ${pdf.numPages}`;
  $("start").disabled=false;
 }catch(err){$("pdfInfo").textContent="خواندن PDF ناموفق بود: "+err.message;pdf=null;$("start").disabled=true;}
};

function makePrompt(text){
 return `تو مترجم و ویراستار حرفه‌ای انگلیسی به فارسی هستی. متن زیر را با سبک «${$("style").value}» ترجمه کن. وفاداری کامل به معنا، تمام جزئیات، نام‌ها، اعداد، ارجاعات و ساختار استدلال الزامی است. چیزی را خلاصه یا حذف نکن و اطلاعاتی از خودت اضافه نکن. نثر فارسی طبیعی و معیار باشد. فقط ترجمه را برگردان. اگر متن شامل عنوان یا بندهای جداگانه است، ساختار آن را حفظ کن.\n\nمتن:\n${text}`;
}
function extractResponsesText(j){
 if(typeof j.output_text==="string"&&j.output_text.trim()) return j.output_text;
 const out=[];
 for(const item of (j.output||[])){
  for(const c of (item.content||[])){
   if(c.type==="output_text"&&c.text) out.push(c.text);
   else if(c.text) out.push(c.text);
  }
 }
 return out.join("\n").trim();
}
async function readResponse(r){
 const raw=await r.text();
 let j={};
 try{j=raw?JSON.parse(raw):{};}catch{throw Error("پاسخ سرویس قابل خواندن نیست: "+raw.slice(0,400));}
 if(!r.ok) throw Error(j.error?.message||j.message||`خطای API ${r.status}`);
 return j;
}
async function callAI(text){
 const key=$("apiKey").value.trim(), model=$("model").value.trim(), provider=$("provider").value;
 if(!key)throw Error("کلید API سرویس انتخاب‌شده را وارد کن.");
 if(!model)throw Error("شناسه مدل را وارد کن.");
 const prompt=makePrompt(text);
 let url,headers={"Content-Type":"application/json"},body,extract;

 if(provider==="gemini"){
  url="https://generativelanguage.googleapis.com/v1beta/interactions";
  headers["x-goog-api-key"]=key;
  body={model,input:prompt,system_instruction:"You are a professional English-to-Persian book translator. Translate faithfully without summarizing or omitting content.",store:false};
  extract=j=>((j.steps||[]).filter(s=>s.type==="model_output").flatMap(s=>s.content||[]).filter(c=>c.type==="text").map(c=>c.text||"").join("\n")).trim();
 }else if(provider==="openai"||provider==="xai"){
  url=provider==="openai"?"https://api.openai.com/v1/responses":"https://api.x.ai/v1/responses";
  headers.Authorization="Bearer "+key;
  body={model,instructions:"You are a professional English-to-Persian book translator. Translate faithfully without summarizing or omitting content.",input:prompt};
  extract=extractResponsesText;
 }else{
  url="https://openrouter.ai/api/v1/chat/completions";
  headers.Authorization="Bearer "+key;
  headers["HTTP-Referer"]=location.origin;
  headers["X-Title"]="BookFlow AI";
  body={model,messages:[{role:"system",content:"You are a professional English-to-Persian book translator. Translate faithfully without summarizing or omitting content."},{role:"user",content:prompt}],temperature:0.2};
  extract=j=>{
   const c=j.choices?.[0]?.message?.content;
   return typeof c==="string"?c:Array.isArray(c)?c.map(x=>x.text||"").join("\n"):"";
  };
 }
 const r=await fetch(url,{method:"POST",headers,body:JSON.stringify(body)});
 const j=await readResponse(r);
 const result=extract(j);
 if(!result)throw Error("پاسخ متنی از مدل دریافت نشد؛ شناسه مدل یا قالب پاسخ را بررسی کن.");
 return result;
}

$("start").onclick=async()=>{
 if(busy||!pdf)return;
 if(!$("apiKey").value.trim()||!$("model").value.trim()){
  $("status").textContent="ابتدا ارائه‌دهنده، کلید API و شناسه مدل را کامل کن.";return;
 }
 busy=true;$("start").disabled=true;$("download").disabled=true;translated=[];docBlob=null;$("bar").style.width="0%";
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
   translated.push(await callAI(chunks[i].text));
   $("bar").style.width=`${Math.round((i+1)/chunks.length*100)}%`;
  }
  const {Document,Packer,Paragraph,TextRun,AlignmentType}=docx;
  const paras=[];
  translated.join("\n\n").split(/\n+/).filter(x=>x.trim()).forEach(t=>paras.push(new Paragraph({bidi:true,alignment:AlignmentType.RIGHT,children:[new TextRun({text:t,rightToLeft:true})]})));
  const d=new Document({sections:[{properties:{},children:paras}]});
  docBlob=await Packer.toBlob(d);
  $("download").disabled=false;
  $("resultInfo").textContent=`ترجمه با ${$("provider").selectedOptions[0].textContent} و مدل ${$("model").value} آماده است.`;
  $("status").textContent="ترجمه تمام شد.";
 }catch(err){
  $("status").textContent="پردازش متوقف شد: "+err.message;
  $("resultInfo").textContent="بخش‌های تکمیل‌شده فقط تا زمانی که این صفحه باز است در حافظه‌اند.";
 }finally{busy=false;$("start").disabled=!pdf;}
};
$("download").onclick=()=>{
 if(!docBlob)return;
 const a=document.createElement("a");a.href=URL.createObjectURL(docBlob);a.download="BookFlow-Translation.docx";a.click();
 setTimeout(()=>URL.revokeObjectURL(a.href),1000);
};
if("serviceWorker" in navigator && location.protocol.startsWith("http"))navigator.serviceWorker.register("./sw.js").catch(()=>{});
