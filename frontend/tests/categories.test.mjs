import test from 'node:test'
import assert from 'node:assert/strict'
import { categoryOptions } from '../src/utils/categories.ts'
test('editor lists both category levels and preserves large string identifiers',()=>{
  const options=categoryOptions([{categoryId:'2000000000000000001',categoryName:'后端',children:[{categoryId:'2000000000000000002',categoryName:'Java'},{categoryId:null,categoryName:null}]}])
  assert.deepEqual(options.map(r=>[r.categoryId,r.categoryName]),[['2000000000000000001','后端'],['2000000000000000002','后端 / Java']])
  assert.deepEqual(categoryOptions([]),[])
})
