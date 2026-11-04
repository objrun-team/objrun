/** A completed HTTP status is not evidence that a model delivered a JSON result. */
export function decodeProviderResponse(raw:string):any{
 if(!raw.trim())throw Error('IncompleteProviderResponse:WhitespaceOnly');
 let value:any;
 try{value=JSON.parse(raw);}catch{throw Error('NonJSONProviderResponse');}
 if(value===null||typeof value!=='object'||Array.isArray(value))throw Error('InvalidProviderResponseShape');
 return value;
}
