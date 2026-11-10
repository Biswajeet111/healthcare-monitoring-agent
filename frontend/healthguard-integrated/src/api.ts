export type Metric = {id:string;date:string;heartRate:number;glucose:number;systolic:number;diastolic:number;steps:number};
export type ChatMessage = {role:'user'|'assistant';text:string;sources?:string[]};
export type UserProfile = {id:number;full_name?:string;email:string};
export type JsonRecord = Record<string,unknown>;
export const DEMO = import.meta.env.VITE_DEMO_MODE === 'true';
export const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/,'');
const chatPath = import.meta.env.VITE_CHAT_PATH || '/rag/ask';
export const asRecord=(x:unknown):JsonRecord=>x && typeof x==='object' && !Array.isArray(x)?x as JsonRecord:{};
export const asList=(x:unknown):JsonRecord[]=>{const r=asRecord(x);const list=Array.isArray(x)?x:(r.items??r.results??r.data??r.medications??r.notifications??r.events??r.alerts??r.history??r.documents);return Array.isArray(list)?list.map(asRecord):[];};
export function friendlyError(e:unknown){return e instanceof Error?e.message:String(e);}
export async function request<T>(path:string, options:RequestInit={}):Promise<T>{
 const token=sessionStorage.getItem('healthguard_token');
 const headers=new Headers(options.headers);
 if(token)headers.set('Authorization',`Bearer ${token}`);
 if(options.body && !(options.body instanceof FormData) && !headers.has('Content-Type'))headers.set('Content-Type','application/json');
 let response:Response;
 try{response=await fetch(BASE+path,{...options,headers});}catch{throw new Error('Cannot reach FastAPI. Check backend server and CORS settings.');}
 if(response.status===401){sessionStorage.removeItem('healthguard_token');window.dispatchEvent(new Event('healthguard-session-expired'));throw new Error('Session expired. Please sign in again.');}
 if(!response.ok){let detail='';try{const obj=await response.json();const d=obj.detail;detail=typeof d==='string'?d:JSON.stringify(d??obj);}catch{detail=response.statusText;}throw new Error(`${response.status}: ${detail.slice(0,220)}`);}
 if(response.status===204)return undefined as T;
 return response.json() as Promise<T>;
}
export async function currentUser():Promise<UserProfile>{const raw=asRecord(await request<unknown>('/auth/me'));const id=Number(raw.id??raw.user_id);if(!Number.isFinite(id))throw new Error('/auth/me did not provide a valid user ID');return {id,email:String(raw.email??''),full_name:String(raw.full_name??raw.name??'')};}
export async function login(email:string,password:string):Promise<UserProfile>{
 let response=await fetch(BASE+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email.trim(),password})});
 if(response.status===415||response.status===422){response=await fetch(BASE+'/auth/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({username:email.trim(),password})});}
 if(!response.ok){const r=asRecord(await response.json().catch(()=>({})));throw new Error(typeof r.detail==='string'?r.detail:`Login failed (${response.status})`);}
 const r=asRecord(await response.json());if(typeof r.access_token!=='string')throw new Error('Login response missing access token');sessionStorage.setItem('healthguard_token',r.access_token);
 return currentUser();
}
export function logout(){sessionStorage.removeItem('healthguard_token');}
export async function fetchMetrics(userId:number):Promise<Metric[]>{
 const raw=await request<unknown>(`/users/${userId}/metrics?limit=500`);
 const rows=asList(raw);if(!Array.isArray(raw)&&!rows.length)throw new Error('Unexpected health metrics response');
 const days=new Map<string,Metric>();
 for(const r of rows){const date=String(r.recorded_at??r.created_at??r.timestamp??'').slice(0,10);const value=Number(r.value);if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!Number.isFinite(value))continue;
 const type=String(r.metric_type??r.type??'').toLowerCase().replace(/[\s-]/g,'_');const m=days.get(date)??{id:date,date,heartRate:NaN,glucose:NaN,systolic:NaN,diastolic:NaN,steps:NaN};
 if(['heart_rate','heartrate','pulse'].includes(type))m.heartRate=value;
 if(['blood_glucose','glucose','blood_sugar'].includes(type))m.glucose=value;
 if(['systolic','systolic_bp','blood_pressure_systolic'].includes(type))m.systolic=value;
 if(['diastolic','diastolic_bp','blood_pressure_diastolic'].includes(type))m.diastolic=value;
 if(['steps','step_count'].includes(type))m.steps=value;
 days.set(date,m);}
 return [...days.values()].sort((a,b)=>a.date.localeCompare(b.date));
}
export async function askAssistant(question:string):Promise<{answer:string;sources:string[]}>{
 const r=asRecord(await request<unknown>(chatPath,{method:'POST',body:JSON.stringify({question})}));
 const answer=r.answer??r.response??r.message;if(typeof answer!=='string')throw new Error('RAG response did not contain an answer; check MedicalQuestionResponse schema.');
 const raw=r.sources??r.citations??r.references;return {answer,sources:Array.isArray(raw)?raw.map(s=>{if(typeof s==='string')return s;const x=asRecord(s);return String(x.title??x.source_title??x.document_title??x.source??JSON.stringify(s));}):[]};
}
export const fetchMedications=(id:number)=>request<unknown>(`/users/${id}/medications`);
export const fetchTodaysDoses=(id:number)=>request<unknown>(`/medications/user/${id}/today`);
export const fetchNotifications=(id:number)=>request<unknown>(`/users/${id}/notifications`);
export const fetchMonitoringEvents=(id:number)=>request<unknown>(`/users/${id}/monitoring/events`);
export const fetchAgentHistory=()=>request<unknown>('/orchestration/history');
export const fetchAgentAlerts=()=>request<unknown>('/orchestration/alerts');
export const fetchAgentSummary=()=>request<unknown>('/orchestration/summary');
export const fetchDocuments=()=>request<unknown>('/documents');
export const fetchRagStatus=()=>request<unknown>('/rag/status');
export const demoMetrics:Metric[]=Array.from({length:14},(_,i)=>{const d=new Date(2026,9,28+i);return {id:String(i),date:d.toISOString().slice(0,10),heartRate:69+(i*7)%14,glucose:92+(i*11)%26,systolic:112+(i*5)%17,diastolic:72+(i*3)%13,steps:4300+(i*1237)%6500};});
