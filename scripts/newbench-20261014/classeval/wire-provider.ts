/** Change only the explicitly authorized provider route, preserving native inference and tools. */
export function withProviderRoute(wire:any,route:any){
 if(typeof route?.providerName!=='string'||typeof route?.providerSlug!=='string'||route.routing?.allow_fallbacks!==false||JSON.stringify(route.routing.only)!==JSON.stringify([route.providerSlug]))throw Error('InvalidPinnedProviderRoute');
 if(route.model&&route.model!==wire.model)throw Error('ProviderModelChanged');
 return {...wire,provider:{...route.routing}};
}
