/* A bounded, interruptible screen choreography. No snapshots or cloned iframes. */
(function(root) {
  function createMotion(env) {
    let full = true, revision = 0, pending = null, restore = null;
    const timers = new Set(), animations = new Set();
    function cancel() {
      revision += 1;
      timers.forEach(id => env.clearTimeout(id)); timers.clear();
      animations.forEach(animation => animation.cancel()); animations.clear();
      if (restore) restore();
      restore = null; pending = null; env.state('idle');
    }
    function later(delay, callback) {
      const id = env.setTimeout(() => {timers.delete(id);callback();},delay);
      timers.add(id);
    }
    function animate(node, frames, options) {
      const animation = env.animate(node,frames,{fill:'both',...options});
      animations.add(animation);
    }
    function transition(from,to,commit,direction = 1) {
      cancel();
      if (!full || !from || from === to || !env.visible(from)) {commit();return;}
      const stamp = revision;
      pending = commit; env.state('exit');
      const inert = from.hasAttribute('inert'); from.setAttribute('inert','');
      restore = () => {if (!inert) from.removeAttribute('inert');};
      const x = direction < 0 ? -1 : 1;
      try {
        animate(from,[{opacity:1,transform:'translate3d(0,0,0)'},{opacity:0,transform:`translate3d(${-x*18}px,-3px,0)`}],{duration:90,easing:'cubic-bezier(.4,0,1,1)'});
        later(90,() => {
          if (stamp !== revision) return;
          restore(); restore = null; pending = null;
          try {
            commit(); env.state('enter');
            animate(to,[{opacity:0,transform:`perspective(1200px) translate3d(${x*34}px,8px,0) rotateY(${-x*2}deg) scale(.988)`},
              {opacity:1,transform:'perspective(1200px) translate3d(0,0,0) rotateY(0deg) scale(1)'}],{duration:340,easing:'cubic-bezier(.16,1,.3,1)'});
            env.parts(to).slice(0,6).forEach((part,index) => {
              animate(part,[{opacity:0,transform:`translate3d(${x*(18+index*3)}px,${6+index*2}px,0)`},{opacity:1,transform:'translate3d(0,0,0)'}],
                {duration:300,delay:index*12,easing:'cubic-bezier(.16,1,.3,1)'});
            });
            env.layers.forEach((layer,index) => {
              animate(layer,[{opacity:0,transform:`translate3d(${-x*115}%,0,0)`},{opacity:index===0?.5:.28,offset:.25},
                {opacity:0,transform:`translate3d(${x*115}%,0,0)`}],{duration:380,delay:index*8,easing:'cubic-bezier(.22,.65,.25,1)'});
            });
            later(400,()=>{if(stamp===revision)cancel();});
          } catch(error) {cancel(); throw error;}
        });
      } catch(error) {cancel();commit();}
    }
    function setFull(value) {
      const commit = pending;
      cancel(); full = Boolean(value);
      // A preference change must not discard the destination of an in-flight click.
      if (commit) commit();
    }
    return {transition,cancel,setFull};
  }
  if(typeof module !== 'undefined') module.exports = {createMotion};
  if(!root.document) return;
  const doc = root.document, stage = doc.getElementById('report-stage');
  if(!stage || typeof stage.animate !== 'function') return;
  const layer = doc.createElement('div'); layer.className='screen-choreography';layer.setAttribute('aria-hidden','true');
  const layers = ['motion-ribbon','motion-trace','motion-glint'].map(cls=>{const el=doc.createElement('i');el.className=cls;layer.append(el);return el;});
  stage.append(layer);
  const controller = createMotion({
    setTimeout:(fn,ms)=>root.setTimeout(fn,ms),clearTimeout:id=>root.clearTimeout(id),
    animate:(node,frames,options)=>node.animate(frames,options),
    visible:node=>node.getClientRects().length>0,
    state:phase=>{stage.dataset.motionPhase=phase;}, layers,
    parts:node=>[...node.querySelectorAll(':scope > .section-kicker, :scope > h2, :scope > .lens-body, :scope > .lens-ticker, :scope > .warning-summary, :scope > dl, :scope > .security-flags-list, :scope > .warning-filters, :scope > .lens-native, :scope > .market-report__heading')],
  });
  // Full motion is the requested product mode, not a modification of OS settings.
  // An explicit Calm option persists locally and always cancels motion immediately.
  let full=true;
  try {full=root.localStorage.getItem('tai-screen-motion')!=='calm';}catch{}
  const toggle=doc.createElement('button');toggle.type='button';toggle.className='screen-motion-toggle';
  toggle.setAttribute('aria-label','Full screen transitions');
  function preference() {
    controller.setFull(full);toggle.textContent='Motion: '+(full?'Full':'Calm');
    toggle.setAttribute('aria-pressed',String(full));doc.body.dataset.screenMotion=full?'full':'calm';
  }
  toggle.addEventListener('click',()=>{full=!full;preference();try{root.localStorage.setItem('tai-screen-motion',full?'full':'calm');}catch{}});
  stage.querySelector('.report-panel__bar').append(toggle);
  preference(); root.ScreenMotion=controller;
  root.addEventListener('pagehide',()=>controller.cancel());
})(typeof window==='undefined'?{}:window);
