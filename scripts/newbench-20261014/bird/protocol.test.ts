import {test,expect} from 'bun:test';
import {cfg,binaryFeedback,fullFeedback,wireBody} from './common.ts';
test('authorized count-bounded protocol uses 32 workers, full request size, and no task dollar ceiling',()=>{
 expect(cfg.initialConcurrency).toBe(32);expect(cfg.independentSamples).toBe(5);expect(cfg.binaryMaxChecks).toBe(5);expect(cfg.perQuestionDollarCap).toBeNull();
 for(const messages of [[{role:'user',content:'small'}],[{role:'user',content:'中文 schema '.repeat(5000)}]])expect(wireBody({messages}).max_tokens).toBe(16384);
});
test('binary feedback discloses only correctness for all error classes',()=>{
 for(const g of [{passed:false,errorType:'OperationalError',message:'sensitive column'}, {passed:false,errorType:'ResultMismatch',gold:'secret'}, {passed:true,rows:['secret']}])expect(binaryFeedback(g)).toBe(g.passed?'passed':'failed');
 expect(fullFeedback({passed:false,errorType:'ResultMismatch',gold:'secret'})).toBe('failed: result mismatch');
});
test('all arms keep model provider reasoning profile and constrained native hand-in',()=>{
 const w=wireBody({messages:[],tools:[{type:'function',function:{name:'submit',parameters:{type:'object',properties:{answer:{type:'string'}}}}},{type:'function',function:{name:'verify',parameters:{}}}],tool_choice:{type:'function',function:{name:'submit'}}});
 expect(w.model).toBe('deepseek/deepseek-v4.1-flash');expect(w.provider.only).toEqual(['digitalocean']);expect(w.provider.allow_fallbacks).toBe(false);expect(w.reasoning).toEqual({enabled:true,effort:'high',exclude:false});expect(w.max_tokens).toBe(16384);expect(w.tools.length).toBe(1);expect(w.tools[0].function.name).toBe('submit');
});
