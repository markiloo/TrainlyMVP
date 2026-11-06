const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function playerContext(){
  const listeners=new Map();
  const video={currentTime:20,paused:true,pause(){this.paused=true},play(){this.paused=false;return Promise.resolve()},
    addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn)},
    removeEventListener(type,fn){listeners.get(type)?.delete(fn)}};
  const button={focus(){},onclick:null};
  const quiz={innerHTML:'',querySelector(){return button}};
  const document={querySelector(selector){return {'#app':{},'#toast':{},'#player':video,'#quiz-area':quiz,'#return-to-question':button}[selector]}};
  const context=vm.createContext({document,setTimeout,clearTimeout});
  vm.runInContext(fs.readFileSync('static/app.js','utf8').replace(/\bboot\(\);\s*$/,''),context);
  vm.runInContext("S.module={questions:[]};S.activeQuestion=null;S.reviewReturn=null;S.asked=new Set();toast=()=>{};showQuestion=(q,retry)=>{S.testQuestion={id:q.id,retry}}",context);
  const emit=type=>[...(listeners.get(type)||[])].forEach(fn=>fn());
  const review=()=>vm.runInContext("reviewExplanation({id:'q',explanation_link:{start:2,end:5,text:'Source'}})",context);
  return {context,video,quiz,listeners,emit,review};
}

test('review ends at its boundary, opens retry, and removes listeners',()=>{
  const c=playerContext();c.review();assert.equal(c.video.currentTime,2);
  assert.equal(vm.runInContext('S.reviewReturn',c.context),20);
  c.video.currentTime=5;c.emit('timeupdate');assert.equal(c.video.paused,true);
  assert.equal(vm.runInContext('S.testQuestion.retry',c.context),true);
  assert.ok([...c.listeners.values()].every(set=>set.size===0));
});
test('seeking outside the clip returns to the retry form',()=>{
  const c=playerContext();c.review();c.video.currentTime=9;c.emit('seeking');
  assert.equal(vm.runInContext('S.testQuestion.id',c.context),'q');
});
test('an active unanswered checkpoint takes priority over review',()=>{
  const c=playerContext();c.review();vm.runInContext("S.activeQuestion='required'",c.context);
  c.emit('timeupdate');assert.equal(vm.runInContext('S.testQuestion',c.context),undefined);
  assert.equal(vm.runInContext('S.explanationReview',c.context),null);
});
test('continuing restores the original position and checks unanswered questions',()=>{
  const c=playerContext();c.review();
  vm.runInContext('S.testChecked=null;checkQuestions=t=>{S.testChecked=t;S.activeQuestion="checkpoint"};continueLearning()',c.context);
  assert.equal(c.video.currentTime,20);assert.equal(c.video.paused,true);
  assert.equal(vm.runInContext('S.testChecked',c.context),20);
  assert.equal(vm.runInContext('S.reviewReturn',c.context),null);
});
test('cancelling a review repeatedly leaves no media listeners',()=>{
  const c=playerContext();c.review();c.review();vm.runInContext('cancelExplanationReview()',c.context);
  assert.ok([...c.listeners.values()].every(set=>set.size===0));
});
