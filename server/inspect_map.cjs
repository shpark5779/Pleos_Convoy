// Read-only WebView inspection for the emulator demo. Never output URLs or session tokens.
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const adb = path.join(process.env.LOCALAPPDATA, 'Android/Sdk/platform-tools/adb.exe');
const device = process.argv[2], port = Number(process.argv[3] || 9222);
const command = (...args) => execFileSync(adb, ['-s', device, ...args], {encoding:'utf8', timeout:15000});

(async () => {
  const activity = command('shell','dumpsys','activity','activities').split('\n')
    .find(s=>/mResumedActivity|topResumedActivity/.test(s))?.trim() || null;
  const pid = command('shell','pidof','com.example.pleosprojectv01.convoy').trim().split(/\s+/)[0];
  const sockets = command('shell','cat','/proc/net/unix');
  const socket = sockets.split('\n').map(s=>s.trim().split(/\s+/).at(-1))
    .find(s=>s === '@webview_devtools_remote_'+pid);
  if (!socket) throw Error('Convoy WebView debug socket is not ready');
  command('forward', 'tcp:'+port, 'localabstract:'+socket.slice(1));
  const pages = await (await fetch('http://127.0.0.1:'+port+'/json')).json();
  const page = pages.find(p=>p.type==='page' && p.url.includes('/journey'));
  if (!page) throw Error('Journey WebView page is not ready');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const result = await new Promise((resolve,reject)=>{
    const timeout = setTimeout(()=>{ws.close();reject(Error('WebView read timeout'));},15000);
    ws.addEventListener('error',()=>{clearTimeout(timeout);reject(Error('WebView connection failed'));});
    ws.addEventListener('open',()=>ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{
      expression:`JSON.stringify({plan_version:room?.plan_version,route_version:routesVersion,
        waypoint_count:room?.waypoints.length,map_ready:mapReady,map_status:$('mapStatus').textContent,
        status:$('status').textContent,auto_refresh:autoRefreshPlan,
        vehicle_labels:Object.keys(room?.members||{}).map(id=>({name:room.members[id].name,
          own:id===session.memberId,label:vehicleLabel(id)})),
        map_markers:[...$('map').contentDocument.querySelectorAll('img')].filter(i=>i.src.startsWith('data:image/svg+xml'))
          .map(i=>{const svg=new DOMParser().parseFromString(decodeURIComponent(i.src.slice(i.src.indexOf(',')+1)),'image/svg+xml');
            return {label:svg.querySelector('text')?.textContent,color:svg.querySelector('path,circle')?.getAttribute('fill')};}),
        members:Object.values(room?.members||{}).map(m=>({name:m.name,location:m.location})),
        routes:Object.values(routes).map(r=>({meters:r.meters,waypoint_count:r.waypoints?.length,
          point_count:(r.segments||[]).reduce((s,p)=>s+p.length,0)}))})`,returnByValue:true}})));
    ws.addEventListener('message',event=>{const r=JSON.parse(event.data);if(r.id!==1)return;
      clearTimeout(timeout);ws.close();
      if(r.result?.exceptionDetails)reject(Error('Journey state could not be read'));
      else resolve(JSON.parse(r.result.result.value));
    });
  });
  console.log(JSON.stringify({device,activity,...result}));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
