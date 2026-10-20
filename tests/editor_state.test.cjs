const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

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
