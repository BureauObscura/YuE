let token = '';
export function setToken(value:string){ token=value; }
export async function api<T>(path:string,method='GET',data?:unknown):Promise<T>{
  const response=await fetch(path,{method,headers:{...(data!==undefined?{'Content-Type':'application/json'}:{}),...(method!=='GET'?{'X-Studio-Token':token}:{})},body:data===undefined?undefined:JSON.stringify(data)});
  if(!response.ok){let message=`Request failed (${response.status})`;try {const error=await response.json();message=error.error||message;}catch{}throw new Error(message);}
  return response.json();
}
export function fileData(file:File):Promise<string>{return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('The file could not be read.'));reader.readAsDataURL(file);});}
