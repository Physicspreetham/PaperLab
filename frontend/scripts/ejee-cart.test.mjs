import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createCart,addItem,removeItem,validateStore } from '../src/lib/cartModel.js';
import { createDraft,importBlocks,validateDraft } from '../src/lib/builderModel.js';
import { flattenDraft } from '../src/lib/numbering.js';
import { readFile } from 'node:fs/promises';

test('regular and EJEE questions with overlapping IDs coexist and remove independently',()=>{
 const ordinary={paperId:1,number:'1',qtype:'scq'};
 const ejee={...ordinary,library:'ejee'};
 let cart=addItem(createCart(),ordinary).cart;
 cart=addItem(cart,ejee).cart;
 assert.equal(cart.items.length,2);
 assert.equal(addItem(cart,ejee).reason,'duplicate');
 const store=validateStore({carts:[cart],activeId:cart.id}).store;
 assert.equal(store.carts[0].items[1].library,'ejee');
 const removed=removeItem(cart,1,'1','ejee').cart;
 assert.equal(removed.items.length,1);
 assert.equal(removed.items[0].library,undefined);
});

test('cart to builder and persisted draft preserve EJEE identity through sheet ordering',()=>{
 const items=[{paperId:1,number:'1',qtype:'scq'},{paperId:1,number:'1',qtype:'scq',library:'ejee'}];
 const imported=importBlocks(createDraft('assignment'),items);
 assert.equal(imported.added.length,2);
 const loaded=validateDraft(JSON.parse(JSON.stringify(imported.draft))).draft;
 assert.deepEqual(flattenDraft(loaded).map(b=>b.library),[undefined,'ejee']);
 assert.equal(importBlocks(loaded,items).added.length,0);
});

test('API client routes EJEE and ordinary IDs to separate endpoints',async()=>{
 const original=globalThis.fetch;
 const calls=[];
 globalThis.fetch=async url=>{ calls.push(url);return {ok:true,status:200,json:async()=>({})}; };
 try {
  const source=(await readFile(new URL('../src/lib/api.js',import.meta.url),'utf8')).replaceAll('import.meta.env','({})');
  const {api}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
  await api.getQuestion(1,'4','ejee');await api.getQuestion(1,'4');await api.getPaper(1,'ejee');
  assert.deepEqual(calls,['/api/ejee/library/papers/1/questions/4','/api/papers/1/questions/4','/api/ejee/library/papers/1']);
 } finally {globalThis.fetch=original;}
});
