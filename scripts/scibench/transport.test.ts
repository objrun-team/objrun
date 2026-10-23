import {test,expect} from 'bun:test';
import {decodeProviderResponse} from './transport.ts';
test('HTTP200 whitespace keepalive without completion is an infrastructure failure',()=>{
 expect(()=>decodeProviderResponse(('\n         \n').repeat(100))).toThrow('IncompleteProviderResponse:WhitespaceOnly');
});
test('partial JSON cannot manufacture a candidate or valid grade',()=>{
 expect(()=>decodeProviderResponse('{"choices":[')).toThrow('NonJSONProviderResponse');
});
test('normal JSON with leading keepalives remains valid',()=>{
 expect(decodeProviderResponse('\n   \n{"id":"fixture","choices":[]}').id).toBe('fixture');
});
