'use strict';
const items = window.ITEM_ART;
const labels = {weapon:'Weapons',ammo:'Ammunition',armour:'Armour',potion:'Food & potions',ingredient:'Ingredients',book:'Books',misc:'Tools & supplies',light:'Light',gold:'Coin',quest:'Quest items'};
const state = {category:'all',view:'new',query:'',visible:[],selected:0};
const grid = document.querySelector('#grid');
const dialog = document.querySelector('#detail');
const newPath = item => `../assets/sprites/items/${item.id}.png`;
const oldPath = item => `../archive/inventory-icons/2026-10-22/${item.original}`;
const image = (src,alt,old=false) => {const img=document.createElement('img');img.src=src;img.alt=alt;img.loading='lazy';img.decoding='async';if(old)img.className='original-image';return img;};
function render(){
  state.visible=items.filter(item=>(state.category==='all'||item.category===state.category)&&`${item.name} ${item.id}`.toLowerCase().includes(state.query.toLowerCase()));
  grid.replaceChildren();
  state.visible.forEach((item,index)=>{
    const card=document.createElement('button');card.className='item';card.type='button';card.setAttribute('aria-label',`Inspect ${item.name}`);card.dataset.item=item.id;
    const thumb=document.createElement('span');thumb.className=`thumb ${state.view}`;
    if(state.view==='compare'){
      thumb.append(image(oldPath(item),`Original ${item.name}`,true),image(newPath(item),`New ${item.name}`));
      for(const [cls,text] of [['old','ORIGINAL'],['new','NEW']]){const tag=document.createElement('span');tag.className=`thumb-label ${cls}`;tag.textContent=text;thumb.append(tag);}
    }else{thumb.append(image(state.view==='new'?newPath(item):oldPath(item),item.name,state.view==='original'));}
    const name=document.createElement('span');name.className='item-name';name.textContent=item.name;
    const category=document.createElement('span');category.className='item-cat';category.textContent=labels[item.category]||item.category;
    const number=document.createElement('span');number.className='item-id';number.textContent=String(items.indexOf(item)+1).padStart(3,'0');
    card.append(thumb,name,category,number);card.addEventListener('click',()=>showDetail(index));grid.append(card);
  });
  document.querySelector('#count').textContent=`${state.visible.length} object${state.visible.length===1?'':'s'}`;
  document.querySelector('#empty').hidden=state.visible.length>0;
}
function showDetail(index){
  if(!state.visible.length)return;
  state.selected=(index+state.visible.length)%state.visible.length;const item=state.visible[state.selected];
  document.querySelector('#detail-name').textContent=item.name;
  document.querySelector('#detail-category').textContent=labels[item.category]||item.category;
  document.querySelector('#detail-id').textContent=item.id;
  for(const [id,path] of [['new',newPath(item)],['old',oldPath(item)]]){const img=document.querySelector(`#detail-${id}`);img.src=path;img.alt=`${id==='new'?'New':'Original'} ${item.name}`;document.querySelector(`#download-${id}`).href=path;}
  document.querySelector('#fallback-label').textContent=item.originalFallback?'Category fallback':'64 × 64';
  if(!dialog.open)dialog.showModal();
}
const categories=document.querySelector('.categories');
for(const [id,label] of [['all','All objects'],...Object.entries(labels)]){
  const button=document.createElement('button');button.textContent=label;button.className=id==='all'?'active':'';button.type='button';button.dataset.category=id;button.setAttribute('aria-pressed',String(id==='all'));
  button.addEventListener('click',()=>{state.category=id;for(const b of categories.children){const selected=b===button;b.classList.toggle('active',selected);b.setAttribute('aria-pressed',String(selected));}render();});categories.append(button);
}
document.querySelector('#search').addEventListener('input',event=>{state.query=event.target.value;render();});
document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{state.view=button.dataset.view;document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('selected',b===button);b.setAttribute('aria-pressed',String(b===button));});render();}));
document.querySelectorAll('[data-section]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-section]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button));document.querySelector(`#${b.dataset.section}`).hidden=b!==button;});}));
document.querySelector('#size').addEventListener('input',event=>document.documentElement.style.setProperty('--tile',`${event.target.value}px`));
document.querySelector('#close-detail').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}});
document.querySelector('#clear-search').addEventListener('click',()=>{state.query='';document.querySelector('#search').value='';document.querySelector('[data-category="all"]').click();});
document.addEventListener('keydown',event=>{if(dialog.open){if(event.key==='ArrowRight'){event.preventDefault();showDetail(state.selected+1);}if(event.key==='ArrowLeft'){event.preventDefault();showDetail(state.selected-1);}}else if(event.key==='/'&&event.target.tagName!=='INPUT'){event.preventDefault();document.querySelector('#search').focus();}});
render();
