/* Lightweight route replay guidance. This is not the licensed TMAP navigation SDK. */
(function(root) {
  'use strict';
  const R=6371000, rad=d=>d*Math.PI/180;
  function distance(a,b){const dy=rad(b[1]-a[1]),dx=rad(b[0]-a[0]);return 2*R*Math.asin(Math.min(1,Math.sqrt(Math.sin(dy/2)**2+Math.cos(rad(a[1]))*Math.cos(rad(b[1]))*Math.sin(dx/2)**2)))}
  function project(point,edge){
    const scale=Math.cos(rad(point[1])),x=(edge.b[0]-edge.a[0])*scale,y=edge.b[1]-edge.a[1];
    const t=Math.max(0,Math.min(1,((point[0]-edge.a[0])*scale*x+(point[1]-edge.a[1])*y)/(x*x+y*y||1)));
    const p=[edge.a[0]+(edge.b[0]-edge.a[0])*t,edge.a[1]+(edge.b[1]-edge.a[1])*t];
    return {point:p,error:distance(point,p),progress:edge.start+edge.length*t,heading:(Math.atan2(x,y)*180/Math.PI+360)%360};
  }
  function closest(model,point,previous){
    let best=null;
    for(const edge of model.edges){const p=project(point,edge);const score=p.error+(previous===undefined?0:Math.abs(p.progress-previous)*.01);if(!best||score<best.score)best={...p,score};}
    return best;
  }
  function build(route){
    const model={route,edges:[],total:0,turns:[]};
    (route.segments||[route.path]).forEach((segment,index)=>{for(let i=1;i<segment.length;i++){const a=segment[i-1],b=segment[i],length=distance(a,b);if(length>0){model.edges.push({a,b,length,start:model.total,segment:index});model.total+=length;}}});
    if(!model.edges.length)throw Error('주행할 도로 경로가 없습니다.');
    let last=0;
    for(const turn of route.turns||[]){if(!turn.point||turn.point.length<2)continue;const p=closest(model,turn.point,last);if(p.error<100&&p.progress+10>=last){model.turns.push({...turn,progress:p.progress});last=p.progress;}}
    return model;
  }
  function update(model,location,previous=null,now=Date.now()/1000){
    if(!location||!Number.isFinite(location.latitude)||!Number.isFinite(location.longitude)||now-location.measured_at>15||location.measured_at>now+5)return {...previous,stale:true};
    const raw=[location.longitude,location.latitude],match=closest(model,raw,previous?.progress),offRoute=match.error>70;
    const progress=offRoute?(previous?.progress||0):Math.max(previous?.progress||0,match.progress),remaining=Math.max(0,model.total-progress);
    const end=model.edges[model.edges.length-1].b,arrived=!offRoute&&remaining<35&&distance(raw,end)<50;
    let speed=null;
    if(previous&&location.measured_at>previous.measuredAt){const dt=location.measured_at-previous.measuredAt;const kph=distance(raw,previous.raw)/dt*3.6;if(dt<=15&&kph<=150)speed=kph;}
    else if(previous&&location.measured_at===previous.measuredAt)speed=previous.speed;
    const next=model.turns.find(t=>t.progress>progress+3);
    return {raw,point:offRoute?raw:match.point,progress,remaining,heading:match.heading,offRoute,stale:false,arrived,speed,
      measuredAt:location.measured_at,next,nextDistance:next?Math.max(0,next.progress-progress):remaining,
      seconds:model.route.seconds*(remaining/model.total)};
  }
  function split(model,progress){
    const passed=[],remaining=[];let passedSegment=-1,remainingSegment=-1;
    for(const e of model.edges){const t=progress>=e.start+e.length-1e-6?1:Math.max(0,Math.min(1,(progress-e.start)/e.length)),p=[e.a[0]+(e.b[0]-e.a[0])*t,e.a[1]+(e.b[1]-e.a[1])*t];
      if(t>0){if(passedSegment===e.segment)passed[passed.length-1].push(p);else passed.push([e.a,p]);passedSegment=e.segment;}
      if(t<1){if(remainingSegment===e.segment)remaining[remaining.length-1].push(e.b);else remaining.push([p,e.b]);remainingSegment=e.segment;}}
    return {passed,remaining};
  }
  const api={distance,build,update,split};root.ConvoyDriving=api;if(typeof module!=='undefined')module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
