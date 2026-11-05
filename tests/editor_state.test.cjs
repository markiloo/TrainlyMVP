const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('selecting a video shows a scrub-ready local preview before processing', () => {
  const video = { style: {}, set src(value) { this.source = value; } };
  const zone = { querySelector: () => null, insertBefore(element) { this.inserted = element; } };
  const input = { files: [{ name: 'training.mp4' }] };
  const document = {
    querySelector(selector) {
      return { '#app': {}, '#toast': {}, '#video-file': input, '.upload-zone': zone,
        '#upload-note': { set textContent(value) { this.message = value; } } }[selector];
    },
    createElement(tag) { assert.equal(tag, 'video'); return video; },
  };
  const context = vm.createContext({ document, URL: { createObjectURL: () => 'blob:training', revokeObjectURL() {} }, setTimeout });
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8').replace(/\bboot\(\);\s*$/, ''), context);
  vm.runInContext("S.module={id:'new-module'};renderKnowledgeTimeline=()=>{};previewSelectedVideo()", context);
  assert.equal(zone.inserted, video);
  assert.equal(video.source, 'blob:training');
  assert.equal(video.controls, true);
});

test('adding another knowledge check retains typed question fields', () => {
  const buttons = new Map();
  const app = {
    innerHTML: '',
    querySelector(selector) {
      if (!buttons.has(selector)) buttons.set(selector, {});
      return buttons.get(selector);
    },
  };
  const fields = {
    '#app': app,
    '#toast': { classList: { add() {}, remove() {} } },
    '#mtitle': { value: 'Training' },
    '#mdesc': { value: '' },
  };
  const questionFields = [
    { dataset: { q: '0', k: 'prompt' }, value: 'What should I do?' },
    { dataset: { q: '0', k: 'explanation' }, value: 'Report the hazard.' },
    { dataset: { q: '0', k: 'at' }, value: '0' },
  ];
  const optionFields = [
    { dataset: { q: '0', option: '0' }, value: 'Report it' },
    { dataset: { q: '0', option: '1' }, value: 'Ignore it' },
  ];
  const document = {
    querySelector(selector) {
      return fields[selector] || app.querySelector(selector);
    },
    querySelectorAll(selector) {
      if (selector === '[data-q][data-k]') return questionFields;
      if (selector === '[data-q][data-option]') return optionFields;
      if (selector === '[data-answer]:checked') return [{ dataset: { answer: '0' }, value: '0' }];
      return [];
    },
  };
  const context = vm.createContext({ document, setTimeout });
  const source = fs.readFileSync('static/app.js', 'utf8').replace(/\bboot\(\);\s*$/, '');
  vm.runInContext(source, context);
  vm.runInContext("S.user={name:'Creator',role:'creator'};S.module={id:'draft',title:'Training',description:'',status:'draft',video:false,duration:0,lessons:[],questions:[{id:'',prompt:'',options:['',''],answer:0,explanation:'',at:0}]};renderEditor()", context);
  assert.match(app.innerHTML, /id="add-question"[^>]*>[^<]*Add knowledge check at playhead/);
  buttons.get('#add-question').onclick();
  const saved = vm.runInContext('S.module.questions.map(q=>({prompt:q.prompt,options:q.options,explanation:q.explanation}))', context);
  assert.equal(saved.length, 2);
  assert.equal(saved[0].prompt, 'What should I do?');
  assert.deepEqual(Array.from(saved[0].options), ['Report it', 'Ignore it']);
  assert.equal(saved[0].explanation, 'Report the hazard.');
});

test('knowledge checks are inserted at the playhead and moved without losing fields', () => {
  const buttons = new Map();
  const app = {
    innerHTML: '',
    querySelector(selector) {
      if (!buttons.has(selector)) {
        buttons.set(selector, { style: {}, classList: { toggle() {}, add() {}, remove() {} } });
      }
      return buttons.get(selector);
    },
  };
  const video = {
    currentTime: 12,
    duration: 30,
    readyState: 4,
    addEventListener() {},
    play() { return Promise.resolve(); },
    pause() {},
  };
  const fields = {
    '#app': app,
    '#toast': { classList: { add() {}, remove() {} } },
    '#mtitle': { value: 'Training' },
    '#mdesc': { value: '' },
    '#mpass': { value: '70' },
    '#draft-player': video,
  };
  const questionFields = [
    { dataset: { q: '0', k: 'prompt' }, value: 'What should I do?' },
    { dataset: { q: '0', k: 'explanation' }, value: 'Report the hazard.' },
  ];
  const optionFields = [
    { dataset: { q: '0', option: '0' }, value: 'Report it' },
    { dataset: { q: '0', option: '1' }, value: 'Ignore it' },
  ];
  const document = {
    querySelector(selector) { return fields[selector] || app.querySelector(selector); },
    querySelectorAll(selector) {
      if (selector === '[data-q][data-k]') return questionFields;
      if (selector === '[data-q][data-option]') return optionFields;
      if (selector === '[data-answer]:checked') return [{ dataset: { answer: '0' }, value: '0' }];
      return [];
    },
  };
  const context = vm.createContext({ document, setTimeout });
  const source = fs.readFileSync('static/app.js', 'utf8').replace(/\bboot\(\);\s*$/, '');
  vm.runInContext(source, context);
  vm.runInContext("S.user={name:'Creator',role:'creator'};S.module={id:'draft',title:'Training',description:'',status:'draft',video:true,duration:30,lessons:[{id:'l1',title:'Lesson',summary:'',start:0,end:30}],questions:[{id:'q1',prompt:'What should I do?',options:['Report it','Ignore it'],answer:0,explanation:'Report the hazard.',at:5}]};renderEditor()", context);

  buttons.get('#addquestion').onclick();
  let saved = vm.runInContext('S.module.questions.map(q=>({at:q.at,prompt:q.prompt}))', context);
  assert.equal(saved.length, 2);
  assert.equal(saved[1].at, 12);

  vm.runInContext('S.selectedQuestion=0', context);
  video.currentTime = 22;
  buttons.get('#move-selected-check').onclick();
  saved = vm.runInContext('S.module.questions.map(q=>({at:q.at,prompt:q.prompt,options:q.options,answer:q.answer,explanation:q.explanation}))', context);
  assert.equal(saved[0].at, 22);
  assert.equal(saved[0].prompt, 'What should I do?');
  assert.deepEqual(Array.from(saved[0].options), ['Report it', 'Ignore it']);
  assert.equal(saved[0].answer, 0);
  assert.equal(saved[0].explanation, 'Report the hazard.');

  assert.match(vm.runInContext("checkTimeError(15,{duration:30,lessons:[{start:0,end:10},{start:20,end:30}]})", context), /lesson range/);
  assert.equal(vm.runInContext("checkTimeError(30,{duration:30,lessons:[{start:0,end:10},{start:20,end:30}]})", context), '');
});

test('removing a choice adjusts the correct answer and preserves the video position', () => {
  const buttons = new Map();
  const app = { innerHTML: '', querySelector(selector) {
    if (!buttons.has(selector)) buttons.set(selector, { style: {}, classList: { toggle() {}, add() {}, remove() {} } });
    return buttons.get(selector);
  } };
  const video = { currentTime: 14, duration: 30, readyState: 4, addEventListener() {} };
  const fields = {
    '#app': app, '#toast': { classList: { add() {}, remove() {} } },
    '#mtitle': { value: 'Training' }, '#mdesc': { value: '' },
    '#mpass': { value: '70' }, '#draft-player': video,
  };
  const remove = { dataset: { removeOption: '0', option: '1' } };
  const document = {
    querySelector(selector) { return fields[selector] || app.querySelector(selector); },
    querySelectorAll(selector) {
      if (selector === '[data-remove-option]') return [remove];
      if (selector === '[data-q][data-option]') return [
        { dataset: { q: '0', option: '0' }, value: 'A' },
        { dataset: { q: '0', option: '1' }, value: 'B' },
        { dataset: { q: '0', option: '2' }, value: 'C' },
      ];
      if (selector === '[data-answer]:checked') return [{ dataset: { answer: '0' }, value: '2' }];
      return [];
    },
  };
  const context = vm.createContext({ document, setTimeout });
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8').replace(/\bboot\(\);\s*$/, ''), context);
  vm.runInContext("S.user={name:'Creator',role:'creator'};S.module={id:'draft',title:'Training',description:'',status:'draft',video:true,duration:30,lessons:[],questions:[{id:'q',prompt:'Prompt',options:['A','B','C'],answer:2,explanation:'Why',at:5}]};renderEditor()", context);
  remove.onclick();
  const result = vm.runInContext('({options:S.module.questions[0].options,answer:S.module.questions[0].answer,seek:S.editorSeek})', context);
  assert.deepEqual(Array.from(result.options), ['A', 'C']);
  assert.equal(result.answer, 1);
  assert.equal(video.currentTime, 14);
});

test('assignment dropdown disables learners already assigned and escapes labels', () => {
  const context = vm.createContext({ document: { querySelector: () => ({}) }, setTimeout });
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8').replace(/\bboot\(\);\s*$/, ''), context);
  const html = vm.runInContext(
    "learnerOptions([{name:'Jamie Lee',email:'jamie@example.com'},{name:'Sam <Admin>',email:'sam@example.com'}],new Set(['jamie@example.com']))",
    context,
  );
  assert.match(html, /<option value="jamie@example.com" disabled>Jamie Lee &mdash; jamie@example.com \(already assigned\)<\/option>/);
  assert.match(html, /<option value="sam@example.com">Sam &lt;Admin&gt; &mdash; sam@example.com<\/option>/);
  assert.equal(vm.runInContext("learnerOptions([],new Set())", context), '');
});

test('call helpers align video content and collect live annotation strokes', () => {
  const context = vm.createContext({ document: { querySelector: () => ({}) }, setTimeout });
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8').replace(/\bboot\(\);\s*$/, ''), context);
  const rect = vm.runInContext(
    "videoContentRect({getBoundingClientRect:()=>({left:10,top:20,width:320,height:180}),videoWidth:360,videoHeight:640},{getBoundingClientRect:()=>({left:10,top:20})})",
    context,
  );
  assert.equal(rect.w, 101.25);
  assert.equal(rect.h, 180);
  assert.equal(rect.x, 109.375);
  assert.equal(rect.y, 0);
  assert.equal(vm.runInContext("callDuration(125)", context), '2:05');
  assert.equal(vm.runInContext("callStatusLabel('missed')", context), 'Missed');
  vm.runInContext(
    "S.call={strokes:[]};handleAnnotation({type:'stroke-start',id:'a',color:'#fff',width:4});handleAnnotation({type:'stroke-point',id:'a',points:[[0.1,0.2],[0.2,0.3]]});",
    context,
  );
  const strokes = vm.runInContext('S.call.strokes', context);
  assert.equal(strokes.length, 1);
  assert.equal(JSON.stringify(strokes[0].points), JSON.stringify([[0.1, 0.2], [0.2, 0.3]]));
  vm.runInContext("handleAnnotation({type:'undo'})", context);
  assert.equal(vm.runInContext('S.call.strokes.length', context), 0);
});

test('creator call inbox renders statuses and callback actions', async () => {
  const target = {
    innerHTML: '',
    querySelector: () => ({ append() {} }),
  };
  const document = {
    querySelector(selector) {
      if (selector === '#main-content') return target;
      if (selector === '#app') return {};
      if (selector === '#toast') return { classList: { add() {}, remove() {} } };
      if (selector === '.titlebar') return { append() {} };
      return null;
    },
    querySelectorAll: () => [],
    createElement: () => ({}),
  };
  const context = vm.createContext({ document, setTimeout });
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8').replace(/\bboot\(\);\s*$/, ''), context);
  vm.runInContext(
    "api=async()=>[{id:'c1',status:'missed',created_at:1700000000,initiated_by:'learner',duration:null,learner:{name:'Jamie Lee',email:'jamie@example.com'},module:{id:'m1',title:'Safety'},learner_online:true}]",
    context,
  );
  await vm.runInContext('renderCalls()', context);
  assert.match(target.innerHTML, /Jamie Lee/);
  assert.match(target.innerHTML, /Safety/);
  assert.match(target.innerHTML, /Missed/);
  assert.match(target.innerHTML, /Call back/);
});

test('call sounds repeat without overlap and stop pending playback', () => {
  const tones=[], timers=new Map();let next=0;
  class AudioContext {
    state='running';currentTime=0;destination={};
    createGain(){return {gain:{setValueAtTime(){},linearRampToValueAtTime(){}},connect(){},disconnect(){}}}
    createOscillator(){const node={frequency:{value:0},connect(){},disconnect(){},start(){tones.push(this.frequency.value)},stop(){}};return node}
  }
  const context=vm.createContext({document:{querySelector:()=>({})},AudioContext,setTimeout:(fn,ms)=>{timers.set(++next,{fn,ms});return next},clearTimeout:id=>timers.delete(id)});
  vm.runInContext(fs.readFileSync('static/app.js','utf8').replace(/\bboot\(\);\s*$/,''),context);
  vm.runInContext("startCallSound('a','outgoing');startCallSound('a','outgoing')",context);
  assert.deepEqual(tones,[440,480]);assert.equal(timers.size,1);
  assert.equal([...timers.values()][0].ms,6000);
  vm.runInContext("startCallSound('b','incoming')",context);
  assert.deepEqual(tones,[440,480,660,660]);assert.equal(timers.size,1);
  const stale=[...timers.values()][0].fn;
  vm.runInContext('stopCallSound()',context);stale();
  assert.equal(timers.size,0);assert.equal(tones.length,4);
});
