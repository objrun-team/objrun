const {request} = require('../client');
const endpoint='http://127.0.0.1:7802/api';
async function main(){
  await request(endpoint,'/declare','',{
    places:[{place:'local'}],
    modes:[{mode:'work',cycles:[
      {cycle:'ask',apiMode:'chat',maxUnits:16,from:[],next:['act'],infer:'fn:infer.dfs'},
      {cycle:'act',maxUnits:16,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}
    ]}],
    agents:[{name:'bot',apis:[['DEEPSEEK_API_KEY','deepseek-v4-flash']],unit:'fn:unit.tools'}]
  });
  const id='vscode-install-check-'+Date.now();
  await request(endpoint,'/tasks','',{id,mode:'work',agent:'bot',place:'local',source:'user',workdir:process.cwd(),solveSeconds:90,description:'这是插件安装连通性测试。不要调用任何工具，不要修改文件。只回复：TgEngin 插件连接成功。'});
  for(let i=0;i<45;i++){
    await new Promise(r=>setTimeout(r,2000));
    const t=await request(endpoint,'/tasks/'+id);
    if(['done','failed'].includes(t.state)){
      const messages=await request(endpoint,'/tasks/'+id+'/messages');
      console.log(JSON.stringify({id,state:t.state,messages:messages.rows.filter(m=>['prompt','call'].includes(m.kind))},null,2));
      if(t.state!=='done')throw Error('模型连通性测试未完成');
      return;
    }
  }
  throw Error('模型连通性测试超时');
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
