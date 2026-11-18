/* BookFlow AI: multi-provider, automatic chapter/paragraph chunking. API key stays in page memory. */
const $=id=>document.getElementById(id);
if(window.pdfjsLib) pdfjsLib.GlobalWorkerOptions.workerSrc="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
let pdf=null, translated=[], docBlob=null, busy=false;

const providerHints={
 gemini:"Gemini از Interactions API استفاده می‌کند. شناسه مدل را از فهرست مدل‌های Google AI Studio بردار.",
 openai:"OpenAI از Responses API استفاده می‌کند. شناسه مدل باید در حساب API تو فعال باشد.",
 xai:"Grok از Responses API رسمی xAI استفاده می‌کند. شناسه مدل را از پنل xAI بردار.",
 openrouter:"OpenRouter از Chat Completions API استفاده می‌کند. شناسه مدل معمولاً به شکل provider/model است."
};
const modelExamples={
 gemini:"شناسه مدل فعال در Google AI Studio",
 openai:"شناسه مدل فعال در حساب OpenAI",
 xai:"شناسه دقیق مدل فعال در حساب xAI",
 openrouter:"شناسه کامل مدل، مانند provider/model"
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

function makePrompt(text,meta){
 const chapterInfo=meta?.chapter? `این متن از فصل «${meta.chapter}» و قسمت ${meta.part} از ${meta.totalParts} است. این توضیح را ترجمه نکن؛ فقط متن اصلی را ترجمه کن. اگر جمله‌ای در مرز دو قسمت ناتمام به نظر می‌رسد، همان متن موجود را دقیق ترجمه کن و چیزی از خودت اضافه نکن.\n\n`:"";
 return `تو مترجم و ویراستار حرفه‌ای انگلیسی به فارسی هستی. متن زیر را با سبک «${$("style").value}» ترجمه کن. وفاداری کامل به معنا، تمام جزئیات، نام‌ها، اعداد، ارجاعات و ساختار استدلال الزامی است. چیزی را خلاصه یا حذف نکن و اطلاعاتی از خودت اضافه نکن. نثر فارسی طبیعی و معیار باشد. فقط ترجمه را برگردان. ساختار عنوان‌ها و پاراگراف‌ها را حفظ کن.\n\n${chapterInfo}متن:\n${text}`;
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
 const raw=await r.text();let j={};
 try{j=raw?JSON.parse(raw):{};}catch{throw Error("پاسخ سرویس قابل خواندن نیست: "+raw.slice(0,400));}
 if(!r.ok) throw Error(j.error?.message||j.message||`خطای API ${r.status}`);
 return j;
}
async function callAI(text,meta){
 const key=$("apiKey").value.trim(), model=$("model").value.trim(), provider=$("provider").value;
 if(!key)throw Error("کلید API سرویس انتخاب‌شده را وارد کن.");
 if(!model)throw Error("شناسه مدل را وارد کن.");
 const prompt=makePrompt(text,meta);
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
  extract=j=>{const c=j.choices?.[0]?.message?.content;return typeof c==="string"?c:Array.isArray(c)?c.map(x=>x.text||"").join("\n"):"";};
 }
 const r=await fetch(url,{method:"POST",headers,body:JSON.stringify(body)});
 const j=await readResponse(r), result=extract(j);
 if(!result)throw Error("پاسخ متنی از مدل دریافت نشد؛ شناسه مدل یا قالب پاسخ را بررسی کن.");
 return result;
}

/* PDF text is reconstructed into visual lines using each text item's vertical position. */
async function extractPdfLines(){
 const pages=[];
 for(let n=1;n<=pdf.numPages;n++){
  const page=await pdf.getPage(n), content=await page.getTextContent(), rows=[];
  for(const item of content.items){
   if(!item.str||!item.str.trim())continue;
   const y=Math.round(item.transform?.[5]||0);
   let row=rows.find(r=>Math.abs(r.y-y)<=2);
   if(!row){row={y,items:[]};rows.push(row);}
   row.items.push({x:item.transform?.[4]||0,text:item.str});
  }
  rows.sort((a,b)=>b.y-a.y);
  const lines=rows.map(r=>r.items.sort((a,b)=>a.x-b.x).map(x=>x.text).join(" ").trim()).filter(Boolean);
  pages.push(lines.join("\n"));
 }
 return pages;
}
const chapterHeading=/^\s*chapter\s+(?:(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b).*$/i;
function detectChapters(pages){
 const lines=pages.join("\n").split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
 const found=[];
 for(let i=0;i<lines.length;i++){
  if(chapterHeading.test(lines[i]))found.push({at:i,title:lines[i]});
 }
 if(!found.length)return [{title:"متن کتاب",text:lines.join("\n\n")}];
 const chapters=[];
 if(found[0].at>0)chapters.push({title:"مقدمه و مطالب پیش از فصل اول",text:lines.slice(0,found[0].at).join("\n\n")});
 for(let i=0;i<found.length;i++){
  const start=found[i].at,end=i+1<found.length?found[i+1].at:lines.length;
  chapters.push({title:found[i].title,text:lines.slice(start,end).join("\n\n")});
 }
 return chapters.filter(c=>c.text.trim());
}
function splitLongParagraph(paragraph,maxChars){
 const pieces=[];let rest=paragraph.trim();
 while(rest.length>maxChars){
  let cut=Math.max(rest.lastIndexOf(". ",maxChars),rest.lastIndexOf("? ",maxChars),rest.lastIndexOf("! ",maxChars),rest.lastIndexOf("; ",maxChars));
  if(cut<Math.floor(maxChars*.55))cut=rest.lastIndexOf(" ",maxChars);
  if(cut<Math.floor(maxChars*.4))cut=maxChars;
  pieces.push(rest.slice(0,cut+1).trim());rest=rest.slice(cut+1).trim();
 }
 if(rest)pieces.push(rest);
 return pieces;
}
function splitChapter(chapter,maxChars=6500){
 const paragraphs=chapter.text.split(/\n\s*\n/).map(p=>p.trim()).filter(Boolean);
 const units=paragraphs.flatMap(p=>p.length>maxChars?splitLongParagraph(p,maxChars):[p]);
 const parts=[];let current="";
 for(const unit of units){
  if(current&&current.length+unit.length+2>maxChars){parts.push(current);current=unit;}
  else current=current?current+"\n\n"+unit:unit;
 }
 if(current)parts.push(current);
 return parts;
}
function buildWorkQueue(chapters){
 const queue=[];
 chapters.forEach((chapter,chapterIndex)=>{
  const parts=splitChapter(chapter);
  parts.forEach((part,index)=>queue.push({
   text:part,chapter:chapter.title,chapterIndex:chapterIndex+1,
   part:index+1,totalParts:parts.length
  }));
 });
 return queue;
}

$("start").onclick=async()=>{
 if(busy||!pdf)return;
 if(!$("apiKey").value.trim()||!$("model").value.trim()){
  $("status").textContent="ابتدا ارائه‌دهنده، کلید API و شناسه مدل را کامل کن.";return;
 }
 busy=true;$("start").disabled=true;$("download").disabled=true;translated=[];docBlob=null;$("bar").style.width="0%";
 try{
  $("status").textContent="در حال خواندن متن و شناسایی فصل‌ها...";
  const pages=await extractPdfLines();
  if(!pages.some(p=>p.trim()))throw Error("متن قابل استخراج پیدا نشد. احتمالاً PDF اسکن‌شده است.");
  const chapters=detectChapters(pages), queue=buildWorkQueue(chapters);
  if(!queue.length)throw Error("متنی برای ترجمه پیدا نشد.");
  for(let i=0;i<queue.length;i++){
   const item=queue[i];
   $("status").textContent=`فصل ${item.chapterIndex} از ${chapters.length} | قسمت ${item.part} از ${item.totalParts} | درخواست ${i+1} از ${queue.length}`;
   translated.push(await callAI(item.text,item));
   $("bar").style.width=`${Math.round((i+1)/queue.length*100)}%`;
  }
  const {Document,Packer,Paragraph,TextRun,AlignmentType}=docx, paras=[];
  translated.forEach((block,index)=>{
   block.split(/\n+/).filter(x=>x.trim()).forEach(t=>paras.push(new Paragraph({bidi:true,alignment:AlignmentType.RIGHT,children:[new TextRun({text:t,rightToLeft:true})]})));
   if(index<translated.length-1)paras.push(new Paragraph({text:""}));
  });
  const d=new Document({sections:[{properties:{},children:paras}]});
  docBlob=await Packer.toBlob(d);$("download").disabled=false;
  $("resultInfo").textContent=`ترجمه ${chapters.length} فصل شناسایی‌شده در ${queue.length} قسمت، با ${$("provider").selectedOptions[0].textContent} و مدل ${$("model").value} آماده است.`;
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
if("serviceWorker" in navigator&&location.protocol.startsWith("http"))navigator.serviceWorker.register("./sw.js").catch(()=>{});
