import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDraft,importBlocks,setDraftMode,setKeyOverride,validateDraft } from '../src/lib/builderModel.js';
import { assignNumbers,flattenDraft } from '../src/lib/numbering.js';
import { dressQuestion } from '../src/lib/paperDress.js';
import { splitTopBlocks } from '../src/lib/flowsplit.js';

test('EJEE bare statement receives one visible generated number before the figure and options',()=>{
 const source=[{kind:'text',html:'<p>A drop of liquid has diameter D.</p>'},{kind:'fig',url:'/diagram.png'},{kind:'text',html:'<p>A) 2</p><p>B) 4</p>'}];
 const numbered=dressQuestion(source,{numbers:[9]});
 assert.equal(splitTopBlocks(numbered[0].html)[0],'<ol start="9"><li>A drop of liquid has diameter D.</li></ol>');
 assert.equal(numbered[1],source[1]);
 assert.equal(source[0].html,'<p>A drop of liquid has diameter D.</p>');
 const reordered=dressQuestion(source,{numbers:[2]});
 assert.match(reordered[0].html,/start="2"/);
 assert.doesNotMatch(reordered[0].html,/start="9"/);
 assert.equal(dressQuestion(numbered,{numbers:[3]})[0].html,'<ol start="3"><li>A drop of liquid has diameter D.</li></ol>');
});

test('populated paper switches to flat assignment and back without losing identities or answers',()=>{
 let draft=importBlocks(createDraft('paper','My physics sheet'),[
  {paperId:1,number:'4',qtype:'num',library:'ejee'},
  {paperId:2,number:'1',qtype:'scq'},
  {paperId:1,number:'5',qtype:'msq',library:'ejee'}
 ]).draft;
 const before=flattenDraft(draft);const first=before[0].blockId;
 draft=setKeyOverride(draft,first,0,'B');
 const assignment=setDraftMode(draft,'assignment');
 assert.equal(assignment.mode,'assignment');assert.equal(assignment.title,'My physics sheet');
 assert.equal(assignment.sections.length,1);assert.equal(assignment.sections[0].locked,true);
 assert.deepEqual(flattenDraft(assignment).map(b=>b.blockId),before.map(b=>b.blockId));
 assert.deepEqual(assignment.blocks,draft.blocks);assert.deepEqual(assignment.keyOverride,draft.keyOverride);
 assert.equal(assignNumbers(flattenDraft(assignment)).total,3);
 const reloaded=validateDraft(JSON.parse(JSON.stringify(assignment))).draft;
 assert.equal(reloaded.mode,'assignment');assert.equal(flattenDraft(reloaded).length,3);
 const paper=setDraftMode(reloaded,'paper');
 assert.equal(paper.sections.length,3);assert.deepEqual(paper.blocks,draft.blocks);
 assert.deepEqual(paper.keyOverride,draft.keyOverride);
 assert.equal(setDraftMode(paper,'paper'),paper);
});

