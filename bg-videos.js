// Single source of truth for background video URLs.
// Loaded by both / (random pick on each refresh) and /void/ (cycle via arrows).
// To add a new video: upload to R2, then append its URL to this array.
var BG_VIDEOS = [
  'https://cdn.bluishvoid.com/bvbg01.mp4',
  'https://cdn.bluishvoid.com/bvbg02.mp4',
  'https://cdn.bluishvoid.com/bvbg03.mp4',
  'https://cdn.bluishvoid.com/bvbg04.mp4',
  'https://cdn.bluishvoid.com/bvbg05.mp4',
  'https://cdn.bluishvoid.com/bvbg06.mp4',
  'https://cdn.bluishvoid.com/bvbg07.mp4',
  'https://cdn.bluishvoid.com/bvbg08.mp4',
  'https://cdn.bluishvoid.com/bvbg09.mp4',
  'https://cdn.bluishvoid.com/bvbg11.mp4',
];
// Mobile renditions: same clips at 720p (2-10 MB vs 244-1,036 MB) as
// bvbgXX-m.mp4 on R2. The full-size files were ~99% of ALL mobile traffic
// (a phone streamed — and re-streamed on loop — up to a gigabyte of
// background). Wrap every src pick in this; new uploads need BOTH files.
function bgVideoUrl(u){
  return (window.matchMedia && window.matchMedia('(max-width:768px)').matches)
    ? u.replace(/\.mp4$/, '-m.mp4') : u;
}
