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
  buttons.get('#addquestion').onclick();
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
