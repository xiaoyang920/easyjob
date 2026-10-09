import test from 'node:test'
import assert from 'node:assert/strict'
import {chartCeiling,chartPoints,spreadsheetBlob} from '../src/utils/statistics.ts'

test('empty and zero charts use a finite scale',()=>{
  assert.equal(chartCeiling([]),1);assert.equal(chartCeiling([0,0]),1)
  assert.deepEqual(chartPoints([0,0],1),[{x:48,y:178},{x:632,y:178}])
})
test('fractional reading minutes retain their scale and counts share a zero baseline',()=>{
  assert.equal(chartCeiling([.01,.02]),.02)
  const points=chartPoints([0,.01,.02],.02)
  assert.equal(points[2].y,32);assert.equal(points[0].y,178);assert.equal(points[1].y,105)
  assert.equal(chartCeiling([0,3,47]),50)
  assert.ok(chartPoints([5],5).every(p=>Number.isFinite(p.x) && Number.isFinite(p.y)))
})
test('JSON permission and backend errors are never downloaded as Excel',async()=>{
  await assert.rejects(spreadsheetBlob(new Blob([JSON.stringify({code:403,message:'只有管理员可以导出'})])),/只有管理员可以导出/)
  await assert.rejects(spreadsheetBlob(new Blob(['<html>server error</html>'])),/导出未成功/)
  await assert.rejects(spreadsheetBlob({data:'bad'}),/格式异常/)
})
test('xlsx ZIP signature is accepted without copying the full file',async()=>{
  const blob=new Blob([new Uint8Array([0x50,0x4b,0x03,0x04,0,0])],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
  assert.equal(await spreadsheetBlob(blob),blob)
})
