import {readFileSync,writeFileSync} from 'node:fs';
const job = JSON.parse(readFileSync(new URL('./composition/export-job.json', import.meta.url), 'utf8').replace(/^\uFEFF/,''));
const response = await fetch(`http://localhost:3017/api/render/${encodeURIComponent(job.jobId)}/progress`);
if (!response.ok) throw new Error(`Progress endpoint returned ${response.status}`);
const decoder = new TextDecoder();
let buffer = '', lastStage = '', lastProgress = -10;
for await (const chunk of response.body) {
  buffer += decoder.decode(chunk, {stream:true});
  const events = buffer.split('\n\n');
  buffer = events.pop();
  for (const event of events) {
    const line = event.split('\n').find(line=>line.startsWith('data:'));
    if (!line) continue;
    const state=JSON.parse(line.slice(5).trim());
    if (state.stage !== lastStage || state.progress-lastProgress >=10 || state.status !== 'rendering') {
      console.log(JSON.stringify(state));
      lastProgress=state.progress; lastStage=state.stage;
    }
    if (state.status !== 'rendering') {
      writeFileSync(new URL('./composition/export-result.json', import.meta.url), JSON.stringify(state,null,2));
      if(state.status !== 'complete' && state.status !== 'completed') process.exitCode=1;
    }
  }
}
