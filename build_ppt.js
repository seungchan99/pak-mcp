const pptxgen = require("pptxgenjs");
const p = new pptxgen();
p.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
const W = 13.333, H = 7.5;

const DARK="0E1E2B", NAVY="13324A", TEAL="1FB6C1", AMBER="F2A93B",
      LIGHT="FFFFFF", LBG="F4F7F9", TX="1B2A36", MUT="6B7C89", CARD="FFFFFF";
const F="Malgun Gothic";
const IMG="/sessions/festive-jolly-edison/mnt/MCPProject_pak/";

function frameImg(s,path,x,y,w){
  const h=w/1.404;
  s.addImage({path:IMG+path,x,y,w,h,shadow:{type:"outer",color:"9AA7B0",blur:6,offset:3,angle:90,opacity:0.5}});
  s.addShape(p.ShapeType.roundRect,{x,y,w,h,rectRadius:0.04,fill:{type:"none"},line:{color:TEAL,width:1}});
  return h;
}
function secTitle(s,txt,color){
  s.addShape(p.ShapeType.ellipse,{x:0.5,y:0.52,w:0.18,h:0.18,fill:{color:TEAL}});
  s.addText(txt,{x:0.78,y:0.32,w:12,h:0.6,fontFace:F,fontSize:26,bold:true,color:color||NAVY,align:"left",margin:0});
}
function cap(s,txt,x,y,w){
  s.addText(txt,{x,y,w,h:0.3,fontFace:F,fontSize:10,italic:true,color:MUT,align:"left",margin:0});
}

/* ---------- Slide 1 : Title (dark) ---------- */
let s=p.addSlide(); s.background={color:DARK};
s.addText("전기모터 인버터 방사소음 분석",{x:0.6,y:1.5,w:7.2,h:1.1,fontFace:F,fontSize:40,bold:true,color:LIGHT,align:"left",margin:0});
s.addText("차수(Order) + 공진 주파수대역 분석",{x:0.6,y:2.7,w:7.2,h:0.6,fontFace:F,fontSize:22,color:TEAL,align:"left",margin:0});
s.addText([
  {text:"측정   ",options:{bold:true,color:AMBER}},
  {text:"인버터분리_175_0N_03   ·   ",options:{color:"C9D6DF"}},
  {text:"채널   ",options:{bold:true,color:AMBER}},
  {text:"TOP_50cm (Sound Pressure)",options:{color:"C9D6DF"}},
],{x:0.6,y:3.55,w:7.2,h:0.4,fontFace:F,fontSize:13,align:"left",margin:0});
s.addText("프로젝트 전기모터 · Job ENG_01 · 2,000–14,500 rpm 런업",{x:0.6,y:4.0,w:7.2,h:0.4,fontFace:F,fontSize:13,color:"8CA0AD",align:"left",margin:0});
frameImg(s,"slide_p1.png",8.15,1.35,4.7);
cap(s,"Order APS · TOP_50cm",8.15,5.05,4.7);

/* ---------- Slide 2 : Overview (light) ---------- */
s=p.addSlide(); s.background={color:LBG};
secTitle(s,"분석 개요 & 측정 정보");
// left: measurement info rows
const info=[["프로젝트","전기모터"],["Job / 측정","ENG_01 / 인버터분리_175_0N_03"],
  ["분석 채널","TOP_50cm — Sound Pressure (nr 52)"],["RPM 트랙","CH65 — Rotational Speed (MCU_Mg1)"],
  ["회전 범위","2,000 → 14,500 rpm (런업)"],["소음 가중","dB(lin) 표시 · 핵심 피크 dB(A) 환산"]];
let iy=1.5;
info.forEach(r=>{
  s.addShape(p.ShapeType.roundRect,{x:0.6,y:iy,w:5.9,h:0.62,rectRadius:0.06,fill:{color:CARD},line:{color:"E1E8ED",width:1}});
  s.addText(r[0],{x:0.78,y:iy,w:1.9,h:0.62,fontFace:F,fontSize:12,bold:true,color:TEAL,valign:"middle",margin:0});
  s.addText(r[1],{x:2.65,y:iy,w:3.75,h:0.62,fontFace:F,fontSize:12,color:TX,valign:"middle",margin:0});
  iy+=0.72;
});
// right: 4-step cards
s.addText("분석 구성 · 4 페이지",{x:6.9,y:1.35,w:6,h:0.4,fontFace:F,fontSize:15,bold:true,color:NAVY,margin:0});
const steps=[["P1","Order APS 컬러맵","지배 차수 식별 (order×RPM)"],
  ["P2","주요 차수 Order cut","각 차수 레벨 vs RPM"],
  ["P3","APS 주파수×시간","공진 구조 (고정주파수) 분리"],
  ["P4","평균 스펙트럼","공진 주파수대역 확정"]];
let cy=1.85;
steps.forEach(c=>{
  s.addShape(p.ShapeType.roundRect,{x:6.9,y:cy,w:5.9,h:1.02,rectRadius:0.06,fill:{color:CARD},line:{color:"E1E8ED",width:1}});
  s.addShape(p.ShapeType.roundRect,{x:7.05,y:cy+0.19,w:0.62,h:0.62,rectRadius:0.06,fill:{color:NAVY}});
  s.addText(c[0],{x:7.05,y:cy+0.19,w:0.62,h:0.62,fontFace:F,fontSize:15,bold:true,color:LIGHT,align:"center",valign:"middle",margin:0});
  s.addText(c[1],{x:7.85,y:cy+0.14,w:4.8,h:0.4,fontFace:F,fontSize:14,bold:true,color:TX,margin:0});
  s.addText(c[2],{x:7.85,y:cy+0.52,w:4.8,h:0.4,fontFace:F,fontSize:11.5,color:MUT,margin:0});
  cy+=1.14;
});

/* ---------- generic image+content slide ---------- */
function analysisSlide(title, img, caption, blocks){
  const s=p.addSlide(); s.background={color:LBG};
  secTitle(s,title);
  frameImg(s,img,0.55,1.45,7.1);
  cap(s,caption,0.55,6.5,7.1);
  // right content
  let y=1.5;
  blocks.forEach(b=>{
    s.addShape(p.ShapeType.roundRect,{x:7.95,y,w:4.85,h:b.h,rectRadius:0.06,fill:{color:CARD},line:{color:"E1E8ED",width:1}});
    s.addText(b.head,{x:8.15,y:y+0.12,w:4.5,h:0.35,fontFace:F,fontSize:13.5,bold:true,color:b.hc||TEAL,margin:0});
    s.addText(b.body,{x:8.15,y:y+0.5,w:4.5,h:b.h-0.6,fontFace:F,fontSize:12,color:TX,margin:0,valign:"top",lineSpacingMultiple:1.05});
    y+=b.h+0.2;
  });
  return s;
}

/* ---------- Slide 3 : P1 ---------- */
analysisSlide("P1 · Order APS 컬러맵 — 지배 차수","slide_p1.png",
 "수직 스트라이프 = 회전 차수 · 색 = dB(lin)",
 [{head:"지배 차수",h:1.5,body:"2, 8, 19, 24, 38, 48차\n\n8·24·48은 8의 배수 계열 → 전형적 e-모터/인버터 전자기 가진(극·슬롯·토크리플)."},
  {head:"해석 포인트",h:1.9,body:"· 저차(1–2)가 전 RPM에서 강함\n· 48차는 고회전(8k~)에서 밝은 점 → 공진 교차\n· 좌하단 대각 흐림 = 고정주파수 공진 흔적\n  (차수영역에선 곡선으로 나타남)"}]);

/* ---------- Slide 4 : P2 ---------- */
{
 const s=p.addSlide(); s.background={color:LBG};
 secTitle(s,"P2 · 주요 차수 Order cut (레벨 vs RPM)");
 frameImg(s,"slide_p2.png",0.55,1.45,7.1);
 cap(s,"2·8·19·24·48차 오버레이 · dB(lin) vs RPM","0.55",6.5,7.1);
 // table on right
 const rows=[["차수","거동 / 최고레벨"],
   ["2 (적)","고회전 광대역 지배 · ~84 dB @9–12k"],
   ["8 (녹)","~8,500rpm 급피크 · ~87 dB · 공진의심"],
   ["19 (청)","고회전 상승 · ~78 dB @11–14k"],
   ["24 (흑)","변동 큼 · ~72 dB"],
   ["48 (황)","8k·11–13k 피크 · ~80 dB"]];
 let ty=1.55;
 rows.forEach((r,i)=>{
   const hd=i===0;
   s.addShape(p.ShapeType.rect,{x:7.95,y:ty,w:1.15,h:0.72,fill:{color:hd?NAVY:CARD},line:{color:"E1E8ED",width:1}});
   s.addShape(p.ShapeType.rect,{x:9.10,y:ty,w:3.7,h:0.72,fill:{color:hd?NAVY:CARD},line:{color:"E1E8ED",width:1}});
   s.addText(r[0],{x:7.95,y:ty,w:1.15,h:0.72,fontFace:F,fontSize:12,bold:true,color:hd?LIGHT:TX,align:"center",valign:"middle",margin:0});
   s.addText(r[1],{x:9.22,y:ty,w:3.5,h:0.72,fontFace:F,fontSize:11.5,bold:hd,color:hd?LIGHT:TX,valign:"middle",margin:0});
   ty+=0.72;
 });
 s.addText("→ 특정 RPM의 피크(비단조)는 그 차수가 공진을 통과함을 의미",
   {x:7.95,y:ty+0.15,w:4.85,h:0.8,fontFace:F,fontSize:11.5,italic:true,color:MUT,margin:0});
}

/* ---------- Slide 5 : P3 ---------- */
analysisSlide("P3 · APS 주파수×시간 — 공진 구조","slide_p3.png",
 "런업이라 시간↔RPM 1:1 · 색 = dB(lin)",
 [{head:"읽는 법",h:1.35,body:"· 원점에서 뻗는 대각선 = 차수\n· 수직 고정주파수 선/밴드 = 공진"},
  {head:"관찰",h:1.9,body:"고회전(상단)에서 6.5–7.5 kHz 대역이 밝게 증폭 → 구조/방사 공진대. 고차(48 등)가 이 대역을 통과할 때 방사소음 급증."}]);

/* ---------- Slide 6 : P4 ---------- */
analysisSlide("P4 · 평균 스펙트럼 — 공진 주파수대역","slide_p4.png",
 "런업 전체 평균 → 차수는 뭉개지고 고정주파수만 부각",
 [{head:"광대역 공진 (구조/방사)",h:1.25,hc:AMBER,body:"~1.3–1.5 k · ~3.3–3.5 k · ~6.4–6.8 k(최강) · ~7.4 kHz"},
  {head:"협대역 고정 톤",h:1.25,body:"~1.8 k · ~9.6 k(강) · ~11.5 kHz → 인버터 PWM/전자기 정상 톤 의심"},
  {head:"저주파",h:0.95,body:"200–500 Hz raw 최고 (2차 계열)"}]);

/* ---------- Slide 7 : Crossing (accent) ---------- */
{
 const s=p.addSlide(); s.background={color:LBG};
 secTitle(s,"차수 × 공진 교차 — 핵심 메커니즘");
 s.addText("주파수 = 차수 × RPM / 60  →  교차점 RPM이 Order cut 피크와 일치",
   {x:0.78,y:1.05,w:12,h:0.4,fontFace:F,fontSize:13,italic:true,color:MUT,margin:0});
 const rows=[["차수","공진 대역","발생 RPM","우선순위"],
  ["48차","6.4–6.8 kHz","~8,000–8,500","최우선 (방사 whine)"],
  ["24차","3.3–3.5 kHz","~8,300","중요"],
  ["8차","1.3–1.5 kHz","~9,700–11,000","P2 8차 피크와 연결"]];
 let ty=1.6; const cw=[1.7,3.1,3.0,4.4], cx=[0.6,2.3,5.4,8.4];
 rows.forEach((r,i)=>{
   const hd=i===0, hot=r[0]==="48차";
   for(let j=0;j<4;j++){
     s.addShape(p.ShapeType.rect,{x:cx[j],y:ty,w:cw[j],h:0.78,
       fill:{color:hd?NAVY:(hot?"FDF1DD":CARD)},line:{color:"E1E8ED",width:1}});
     s.addText(r[j],{x:cx[j]+0.12,y:ty,w:cw[j]-0.2,h:0.78,fontFace:F,fontSize:12.5,
       bold:hd||(hot&&j===0),color:hd?LIGHT:(hot&&j===3?"C8811A":TX),valign:"middle",
       align:j===0?"center":"left",margin:0});
   }
   ty+=0.78;
 });
 // dB(A) callouts
 s.addText("핵심 피크 dB(A) 환산 (청감)",{x:0.6,y:4.7,w:6,h:0.4,fontFace:F,fontSize:14,bold:true,color:NAVY,margin:0});
 const dba=[["200–500 Hz","~60–65"],["1.8 kHz 톤","~61"],["6.5 kHz 공진","~53"],["9.6 kHz 톤","~57"],["11.5 kHz 톤","~52"]];
 let dx=0.6;
 dba.forEach(d=>{
   s.addShape(p.ShapeType.roundRect,{x:dx,y:5.2,w:2.35,h:1.35,rectRadius:0.08,fill:{color:CARD},line:{color:"E1E8ED",width:1}});
   s.addText(d[1],{x:dx,y:5.45,w:2.35,h:0.6,fontFace:F,fontSize:26,bold:true,color:TEAL,align:"center",margin:0});
   s.addText("dB(A)",{x:dx,y:6.02,w:2.35,h:0.28,fontFace:F,fontSize:10,color:MUT,align:"center",margin:0});
   s.addText(d[0],{x:dx,y:6.28,w:2.35,h:0.28,fontFace:F,fontSize:11,bold:true,color:TX,align:"center",margin:0});
   dx+=2.45;
 });
}

/* ---------- Slide 8 : Conclusion (dark) ---------- */
s=p.addSlide(); s.background={color:DARK};
s.addShape(p.ShapeType.ellipse,{x:0.5,y:0.55,w:0.18,h:0.18,fill:{color:TEAL}});
s.addText("결론 & 권고",{x:0.78,y:0.35,w:12,h:0.6,fontFace:F,fontSize:26,bold:true,color:LIGHT,margin:0});
const concl=[
 ["지배 소음원","전자기 차수 — 저주파 2차 + 8/24/48차(8배수 전자기 계열)"],
 ["대책 급소","48차 × 6.5 kHz 구조공진 교차 (~8,000–8,500 rpm) = 최강 방사 whine"],
 ["톤 성분","협대역 9.6 kHz · 1.8 kHz 고정 톤 → 인버터 PWM/전자기 정상 톤 의심"],
 ["다음 단계","진동 채널(MOT_Hsg · INV_PM)과 상관 분석 → 구조전달 vs 방사 경로 규명"]];
let yy=1.5;
concl.forEach((c,i)=>{
 s.addShape(p.ShapeType.roundRect,{x:0.6,y:yy,w:12.1,h:1.15,rectRadius:0.06,fill:{color:"152A3B"},line:{color:"24435C",width:1}});
 s.addShape(p.ShapeType.roundRect,{x:0.78,y:yy+0.28,w:0.6,h:0.6,rectRadius:0.3,fill:{color:i===1?AMBER:TEAL}});
 s.addText(String(i+1),{x:0.78,y:yy+0.28,w:0.6,h:0.6,fontFace:F,fontSize:16,bold:true,color:DARK,align:"center",valign:"middle",margin:0});
 s.addText(c[0],{x:1.6,y:yy+0.16,w:3.0,h:0.8,fontFace:F,fontSize:15,bold:true,color:i===1?AMBER:TEAL,valign:"middle",margin:0});
 s.addText(c[1],{x:4.6,y:yy+0.16,w:7.9,h:0.85,fontFace:F,fontSize:13,color:"DCE6EC",valign:"middle",margin:0});
 yy+=1.28;
});

p.writeFile({fileName:"/sessions/festive-jolly-edison/mnt/ATFX/인버터_TOP50cm_소음분석.pptx"}).then(f=>console.log("WROTE",f));
