// Offline test of the map's plan refresh policy. No browser or TMAP requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(__dirname + '/journey.html', 'utf8');
const policy = html.slice(html.indexOf('const autoRefreshPlan='), html.indexOf('const distanceText='));

async function check(enabled) {
  let calls = 0, fail = false;
  const room = {plan_version: 0, members: {a: {role: 'driver', location: null}}};
  const context = vm.createContext({
    URLSearchParams, Date, location: {hash: '#auto_refresh=' + enabled}, room,
    refresh: async () => { calls++; if (fail) throw Error('429'); }, status: () => {},
  });
  vm.runInContext(policy, context);
  const tick = () => vm.runInContext('refreshDemoPlan()', context);
  await tick();
  assert.equal(calls, 0, 'wait for GPS');
  room.members.a.location = {measured_at: Date.now()/1000};
  await tick(); await tick();
  assert.equal(calls, enabled ? 1 : 0, 'one initial request only in demo mode');
  room.plan_version = 1;
  fail = true;
  await tick(); await tick();
  assert.equal(calls, enabled ? 2 : 0, 'one attempt for new plan, no quota retry loop');
  room.plan_version = 2;
  room.members.a.location.measured_at -= 31;
  await tick();
  assert.equal(calls, enabled ? 2 : 0, 'stale GPS cannot cause routing');
}

async function checkRepeatedApplications() {
  let attempts = 0, confirmations = 0;
  const room = {plan_version: 1, revision: 1, proposal: null};
  const context = vm.createContext({URLSearchParams,Date,location:{hash:'#auto_refresh=true'},
    room,session:{memberId:'a'},routesVersion:1,routes:{a:{}},
    render: value => { room.revision=value.revision; },
    call: async (op,body) => {
      assert.equal(op,'applications');
      if(body.state==='requested'){
        attempts++;return {proposal:{applications:{a:{attempt_id:'attempt-'+attempts}}}};
      }
      assert.equal(body.state,'succeeded');assert.equal(body.attempt_id,'attempt-'+attempts);
      confirmations++;return {revision:room.revision+1};
    },
  });
  vm.runInContext(policy,context);
  for(let version=1;version<=3;version++){
    room.plan_version=version;context.routesVersion=version;
    room.proposal={id:'p'+version,status:'approved',applications:{a:{state:'not_requested'}}};
    await vm.runInContext('acknowledgeDemoPlan()',context);
  }
  assert.equal(attempts,3);assert.equal(confirmations,3);
  context.routesVersion=2;
  await vm.runInContext('acknowledgeDemoPlan()',context);
  assert.equal(attempts,3,'an old route cannot acknowledge the new plan');
}

(async () => {
  await check(true); await check(false);
  await checkRepeatedApplications();
  // Parse the entire inline script as well, including the iframe's nested script string.
  const script = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));
  new vm.Script(script);
  console.log('PASS: mixed map initial/changed plan refresh, stale GPS, quota errors, normal mode, JS syntax.');
})().catch(error => { console.error(error); process.exitCode = 1; });
