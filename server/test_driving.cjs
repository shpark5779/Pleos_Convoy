const assert=require('node:assert/strict'),D=require('./driving.js');
const route={segments:[[[127,36],[127.001,36]],[[127.001,36],[127.001,36.001]]],seconds:100,
 turns:[{point:[127.001,36],description:'좌회전'},{point:[127.001,36.001],description:'목적지 도착'}]};
const model=D.build(route),loc=(longitude,latitude,time)=>({longitude,latitude,measured_at:time});
const start=D.update(model,loc(127,36,100),null,100);
assert.equal(start.next.description,'좌회전');assert(start.remaining>150);
const middle=D.update(model,loc(127.0005,36,105),start,105);
assert(middle.remaining<start.remaining);assert(middle.speed>20&&middle.speed<40);
const corner=D.update(model,loc(127.001,36.0001,110),middle,110);
assert.equal(corner.next.description,'목적지 도착');
const off=D.update(model,loc(127.01,36,115),corner,115);
assert(off.offRoute);assert.equal(off.progress,corner.progress);
assert(D.update(model,loc(127.001,36.001,100),corner,130).stale);
const end=D.update(model,loc(127.001,36.001,120),corner,120);
assert(end.arrived);assert(end.remaining<1);
assert(D.split(model,middle.progress).passed.length>0);
assert.equal(D.split(model,model.total).remaining.length,0);
// Disconnected road links must not introduce a fictitious connector distance.
const gaps=D.build({segments:[[[0,0],[.001,0]],[[1,0],[1.001,0]]],seconds:10});
assert(gaps.total<225);
console.log('PASS: progress, next turn, measured speed, off-route, stale GPS, arrival, path splitting and geometry gaps.');
